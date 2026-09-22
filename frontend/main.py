"""FastAPI proxy for a deployed A2A agent with File & Document Upload support (PDF, DOC/DOCX, Images).

The browser talks ONLY to this proxy (same origin, no CORS). The proxy accepts file uploads
(PDFs, Word DOC/DOCX files, and Photos/Images), extracts or uploads them to Google Cloud Storage,
and forwards them to the ADK A2A agent as TextParts or FileParts so Gemini can process them.
"""

import os
import uuid
import io
import pypdf
import docx
from google.cloud import storage
import google.auth
import google.auth.transport.requests
import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types import (
    AgentCard,
    FilePart,
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TextPart,
    TransportProtocol,
)
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

RESOURCE = os.environ["AGENT_ENGINE_RESOURCE_NAME"]
AGENT_DIRECTORY = os.environ.get("AGENT_DIRECTORY", "app")
LOCATION = RESOURCE.split("/locations/")[1].split("/")[0] if "/locations/" in RESOURCE else "us-central1"
PROJECT_ID = RESOURCE.split("/projects/")[1].split("/")[0] if "/projects/" in RESOURCE else "qwiklabs-gcp-01-f419067f0d55"
BUCKET_NAME = f"{PROJECT_ID}-static-assets-bucket"

A2A_BASE = (
    f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/"
    f"{RESOURCE}/api/a2a/{AGENT_DIRECTORY}"
)
A2A_CARD_URL = f"{A2A_BASE}/.well-known/agent-card.json"

_A2UI_MIME = "application/json+a2ui"

_creds, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)


def _auth_headers() -> dict[str, str]:
    _creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }


app = FastAPI()


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    return JSONResponse(
        status_code=200,
        content={
            "parts": [{"kind": "text", "text": f"Error: {type(exc).__name__}: {exc}"}]
        },
    )


_contexts: dict[str, str] = {}
_card: AgentCard | None = None


async def _get_card(client: httpx.AsyncClient) -> AgentCard:
    global _card
    if _card is None:
        resp = await client.get(A2A_CARD_URL)
        resp.raise_for_status()
        card = AgentCard(**resp.json())
        card.url = A2A_BASE
        _card = card
    return _card


def _extract_parts(parts: list) -> list[dict]:
    out: list[dict] = []
    for p in parts:
        root = getattr(p, "root", p)
        if isinstance(root, TextPart) and getattr(root, "text", None):
            out.append({"kind": "text", "text": root.text})
        elif getattr(root, "data", None) is not None:
            meta = getattr(root, "metadata", None) or {}
            mime = meta.get("mimeType") if isinstance(meta, dict) else None
            if mime == _A2UI_MIME:
                out.append({"kind": "a2ui", "data": root.data})
        elif isinstance(root, FilePart):
            uri = getattr(getattr(root, "file", None), "uri", None)
            if uri:
                out.append({"kind": "text", "text": uri})
    return out


def _extract_text_from_pdf(contents: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(contents))
        extracted = []
        for idx, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                extracted.append(f"--- Page {idx + 1} ---\n{text}")
        return "\n".join(extracted)
    except Exception as e:
        return f"[Error parsing PDF: {str(e)}]"


def _extract_text_from_docx(contents: bytes) -> str:
    try:
        doc = docx.Document(io.BytesIO(contents))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception as e:
        return f"[Error parsing DOCX document: {str(e)}]"


def _upload_image_to_gcs(contents: bytes, filename: str, mime_type: str) -> str:
    try:
        gcs_client = storage.Client(project=PROJECT_ID)
        bucket = gcs_client.bucket(BUCKET_NAME)
        ext = filename.split(".")[-1] if "." in filename else "jpg"
        blob_name = f"user_uploads/{uuid.uuid4()}.{ext}"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(contents, content_type=mime_type)
        return f"https://storage.googleapis.com/{BUCKET_NAME}/{blob_name}"
    except Exception as e:
        return f"[GCS Upload Error: {str(e)}]"


@app.post("/chat")
async def chat(
    message: str = Form(""),
    user_id: str = Form("web-user"),
    file: UploadFile | None = File(None),
):
    parts_to_send: list[Part] = []
    file_context_prompt = ""

    if file and file.filename:
        filename = file.filename
        content_type = file.content_type or ""
        contents = await file.read()

        if filename.lower().endswith(".pdf") or "pdf" in content_type:
            pdf_text = _extract_text_from_pdf(contents)
            file_context_prompt = (
                f"\n\n[USER ATTACHED PDF DOCUMENT: '{filename}']\n"
                f"Document Content:\n{pdf_text[:8000]}\n[End of Document]\n"
            )
        elif (
            filename.lower().endswith((".doc", ".docx"))
            or "word" in content_type
            or "officedocument" in content_type
        ):
            docx_text = _extract_text_from_docx(contents)
            file_context_prompt = (
                f"\n\n[USER ATTACHED WORD DOCUMENT: '{filename}']\n"
                f"Document Content:\n{docx_text[:8000]}\n[End of Document]\n"
            )
        elif (
            content_type.startswith("image/")
            or filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))
        ):
            public_url = _upload_image_to_gcs(
                contents, filename, content_type or "image/jpeg"
            )
            file_context_prompt = (
                f"\n\n[USER ATTACHED PHOTO/IMAGE: '{filename}']\n"
                f"Public Image URL: {public_url}\n"
                f"Please analyze this image or incorporate it into the fantasy campaign/character context."
            )
        else:
            file_context_prompt = f"\n\n[USER ATTACHED FILE: '{filename}']"

    final_message_text = (message + file_context_prompt).strip()
    if not final_message_text:
        final_message_text = "Please examine my uploaded document/image."

    parts_to_send.append(Part(root=TextPart(text=final_message_text)))

    parts: list[dict] = []

    async with httpx.AsyncClient(headers=_auth_headers(), timeout=120) as client:
        card = await _get_card(client)
        factory = ClientFactory(
            ClientConfig(
                supported_transports=[
                    TransportProtocol.jsonrpc,
                    TransportProtocol.http_json,
                ],
                httpx_client=client,
            )
        )
        a2a_client = factory.create(card)

        msg = Message(
            message_id=str(uuid.uuid4()),
            role=Role.user,
            parts=parts_to_send,
            context_id=_contexts.get(user_id),
        )

        last_task = None
        got_artifact_update = False
        async for event in a2a_client.send_message(msg):
            if not isinstance(event, tuple):
                continue
            task, update = event
            if task is not None:
                last_task = task
                if getattr(task, "context_id", None):
                    _contexts[user_id] = task.context_id
            if isinstance(update, TaskArtifactUpdateEvent):
                got_artifact_update = True
                parts.extend(_extract_parts(update.artifact.parts))

        if not got_artifact_update and last_task is not None:
            for artifact in getattr(last_task, "artifacts", None) or []:
                parts.extend(_extract_parts(artifact.parts))

    if not parts:
        parts = [{"kind": "text", "text": "(The agent didn't return a reply.)"}]
    return JSONResponse({"parts": parts})


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
