# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import random
from typing import Optional, List, Dict, Any
import requests

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
import uuid
from google.adk.tools import ToolContext
from google.cloud import storage
from google import genai
from google.genai import types
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from a2ui.schema.manager import A2uiSchemaManager
from a2ui.basic_catalog.provider import BasicCatalog
from .a2ui_utils import a2ui_callback

PROJECT_ID = "qwiklabs-gcp-01-f419067f0d55"
BUCKET_NAME = "qwiklabs-gcp-01-f419067f0d55-static-assets-bucket"
AGENT_ENGINE_RESOURCE_NAME = "projects/392896179766/locations/us-central1/reasoningEngines/8984069378383282176"

schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are an expert Fantasy Dungeon Master and TTRPG companion. "
        "You run immersive fantasy campaigns, manage rules, guide adventures, "
        "and track campaign quests in the Firestore database. "
        "Use Python code execution to calculate encounter math, probability, stats, or damage rolls. "
        "Use `fetch_random_magic_item` to generate loot or uncover mysterious magic artifacts for players. "
        "Use `lookup_dnd_rules` to look up official stats for monsters, spells, and equipment. "
        "Use `consult_herbal_docs` to answer questions about herbs, plants, remedies, and potion ingredients from Culpeper's Complete Herbal corpus. "
        "Use `generate_fantasy_item_image` to generate custom visual artwork for weapons, magic items, or quest rewards. "
        "Use `get_quests` to look up available or active quests, and `create_or_update_quest` "
        "to update quest statuses or log new adventures. "
        "Remember player character stats, party history, preferences, and "
        "decisions across sessions using your memory tool."
    ),
    workflow_description="Analyze the user request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


def fetch_random_magic_item() -> Dict[str, Any]:
    """Fetches a random magic item or weapon rules entry from Open5e REST API (listed in public-apis repository).

    Returns:
        JSON containing magic item details, rarity, type, and description.
    """
    try:
        api_key = os.environ.get("OPEN5E_API_KEY")  # Optional API key support via env var if configured
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        url = "https://api.open5e.com/v1/magicitems/?format=json&limit=50"
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])
            if results:
                item = random.choice(results)
                return {
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "rarity": item.get("rarity"),
                    "requires_attunement": item.get("requires_attunement"),
                    "description": item.get("desc"),
                }
            return {"error": "No magic items returned from Open5e API."}
        return {"error": f"Open5e API request failed with status {response.status_code}."}
    except Exception as e:
        return {"error": f"Failed to fetch from Open5e API: {str(e)}"}


def lookup_dnd_rules(category: str, query: str) -> Dict[str, Any]:
    """Looks up official 5e D&D rules, monster stats, or spell details from the D&D 5e API.

    Args:
        category: The category to look up ('monsters', 'spells', 'equipment', 'rules').
        query: The name of the monster, spell, or item (e.g., 'goblin', 'fireball', 'longsword').

    Returns:
        JSON data containing official stats, descriptions, and mechanics.
    """
    try:
        formatted_query = query.lower().replace(" ", "-")
        url = f"https://www.dnd5eapi.co/api/{category.lower()}/{formatted_query}"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return {"error": f"No official {category[:-1] if category.endswith('s') else category} entry found for '{query}'."}
        else:
            return {"error": f"API request failed with status code {response.status_code}."}
    except Exception as e:
        return {"error": f"Failed to query D&D API: {str(e)}"}


def get_firestore_client():
    return firestore.Client(project=PROJECT_ID, database="(default)")


def get_quests(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Reads available or active quest logs from the campaign Firestore database.

    Args:
        status: Optional filter by quest status ('Available', 'In Progress', 'Completed').

    Returns:
        List of quest items containing id, title, status, difficulty, reward_gold, location, description, and assigned_to.
    """
    try:
        db = get_firestore_client()
        quests_ref = db.collection("quests")
        if status:
            query = quests_ref.where("status", "==", status)
            docs = query.stream()
        else:
            docs = quests_ref.stream()

        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            results.append(data)
        return results
    except Exception as e:
        return [{"error": f"Failed to fetch quests from Firestore: {str(e)}"}]


def create_or_update_quest(
    quest_id: str,
    title: str,
    status: str,
    difficulty: str,
    reward_gold: int,
    location: str,
    description: str,
    assigned_to: Optional[str] = None,
) -> str:
    """Creates or updates a campaign quest entry in the Firestore database.

    Args:
        quest_id: Unique identifier for the quest (e.g., 'quest_004').
        title: Title of the quest.
        status: Current status of the quest ('Available', 'In Progress', 'Completed', 'Failed').
        difficulty: Quest difficulty ('Easy', 'Medium', 'Hard', 'Deadly').
        reward_gold: Gold coin reward amount.
        location: In-world location of the quest.
        description: Quest background summary and objectives.
        assigned_to: Name of character or party assigned to this quest.

    Returns:
        Confirmation message.
    """
    try:
        db = get_firestore_client()
        doc_ref = db.collection("quests").document(quest_id)
        quest_data = {
            "id": quest_id,
            "title": title,
            "status": status,
            "difficulty": difficulty,
            "reward_gold": reward_gold,
            "location": location,
            "description": description,
            "assigned_to": assigned_to,
        }
        doc_ref.set(quest_data, merge=True)
        return f"Successfully saved quest '{title}' ({quest_id}) with status '{status}' in Firestore."
    except Exception as e:
        return f"Failed to save quest to Firestore: {str(e)}"


def roll_dice(dice: str = "1d20") -> str:
    """Rolls virtual dice for tabletop roleplaying checks.

    Args:
        dice: Standard dice notation like '1d20', '2d6', '1d8+3'.

    Returns:
        The result of the dice roll.
    """
    try:
        modifier = 0
        if "+" in dice:
            dice_part, mod_part = dice.split("+")
            modifier = int(mod_part.strip())
        elif "-" in dice:
            dice_part, mod_part = dice.split("-")
            modifier = -int(mod_part.strip())
        else:
            dice_part = dice

        count_str, sides_str = dice_part.lower().split("d")
        count = int(count_str.strip()) if count_str.strip() else 1
        sides = int(sides_str.strip())

        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls) + modifier
        return f"Rolled {dice}: {rolls} (Total: {total})"
    except Exception as e:
        return f"Error rolling {dice}: {str(e)}. Please use format like '1d20' or '2d6+2'."


import json

# Load Culpeper's Herbal Corpus Database
HERBAL_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "herbal_database.json")
try:
    with open(HERBAL_DB_PATH, "r", encoding="utf-8") as _f:
        HERBAL_DB = json.load(_f)
except Exception:
    HERBAL_DB = {}


def consult_herbal_docs(query: str) -> Dict[str, Any]:
    """Retrieves lore, medicinal uses, and virtues of herbs, plants, and remedies from Culpeper's The Complete Herbal corpus.

    Args:
        query: The name of an herb (e.g. 'rosemary', 'angelica') or ailment/remedy (e.g. 'fever', 'headache').

    Returns:
        Matches containing excerpt text from the herbal knowledge corpus.
    """
    if not HERBAL_DB:
        return {"error": "Herbal corpus database is not loaded."}
    
    keywords = [k.lower() for k in query.split() if len(k) > 2]
    if not keywords:
        keywords = [query.lower()]

    matches = {}
    for name, text in HERBAL_DB.items():
        name_lower = name.lower()
        text_lower = text.lower()
        if any(kw in name_lower or kw in text_lower for kw in keywords):
            matches[name] = text[:600] + "..." if len(text) > 600 else text
            if len(matches) >= 3:
                break

    if matches:
        return {"query": query, "results": matches}
    return {"error": f"No herbal lore found matching '{query}' in Culpeper's Complete Herbal."}


async def generate_fantasy_item_image(item_name: str, description: str, tool_context: ToolContext) -> Dict[str, Any]:
    """Generates visual artwork for a fantasy item, magic artifact, or monster using gemini-3.1-flash-lite-image model.

    Args:
        item_name: Name of the fantasy item, weapon, artifact, or creature.
        description: Visual details and aesthetic description of the item.
        tool_context: ADK ToolContext used to save the generated image artifact.

    Returns:
        JSON containing the item name, artifact name, and public HTTPS Cloud Storage URL.
    """
    try:
        genai_client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")
        prompt = f"A high quality fantasy tabletop roleplaying game illustration of {item_name}: {description}"
        response = genai_client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )

        image_bytes = None
        mime_type = "image/jpeg"
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    if part.inline_data.mime_type:
                        mime_type = part.inline_data.mime_type
                    break

        if not image_bytes:
            return {"error": "Failed to extract generated image bytes from model response."}

        filename = f"{uuid.uuid4()}.jpg"
        
        # 1. Save artifact to Playground Artifacts panel
        part_obj = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        await tool_context.save_artifact(filename=filename, artifact=part_obj)

        # 2. Upload image bytes to public Cloud Storage bucket
        gcs_client = storage.Client(project=PROJECT_ID)
        bucket = gcs_client.bucket(BUCKET_NAME)
        blob = bucket.blob(f"items/{filename}")
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/items/{filename}"
        return {
            "item_name": item_name,
            "artifact_name": filename,
            "public_url": public_url,
        }
    except Exception as e:
        return {"error": f"Failed to generate item image: {str(e)}"}


async def generate_fantasy_item_video(item_name: str, description: str, tool_context: ToolContext) -> Dict[str, Any]:
    """Generates a short animated video demonstration for a fantasy item, magic artifact, or monster using gemini-omni-flash-preview model in the global region.

    Args:
        item_name: Name of the fantasy item, weapon, artifact, or creature.
        description: Visual details and dynamic action description for the video.
        tool_context: ADK ToolContext used to save the generated video artifact.

    Returns:
        JSON containing item name, artifact name, and public HTTPS Cloud Storage URL.
    """
    try:
        genai_client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")
        prompt = f"Generate a short animated fantasy RPG video showcasing {item_name}: {description}"
        response = genai_client.models.generate_content(
            model="gemini-omni-flash-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["VIDEO"],
            ),
        )

        video_bytes = None
        mime_type = "video/mp4"
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    video_bytes = part.inline_data.data
                    if part.inline_data.mime_type:
                        mime_type = part.inline_data.mime_type
                    break

        if not video_bytes:
            return {"error": "Failed to extract generated video bytes from model response."}

        filename = f"{uuid.uuid4()}.mp4"

        # 1. Save artifact to Playground Artifacts panel
        part_obj = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
        await tool_context.save_artifact(filename=filename, artifact=part_obj)

        # 2. Upload video bytes to public Cloud Storage bucket
        gcs_client = storage.Client(project=PROJECT_ID)
        bucket = gcs_client.bucket(BUCKET_NAME)
        blob = bucket.blob(f"videos/{filename}")
        blob.upload_from_string(video_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/videos/{filename}"
        return {
            "item_name": item_name,
            "artifact_name": filename,
            "public_url": public_url,
        }
    except Exception as e:
        return {"error": f"Failed to generate item video: {str(e)}"}


async def generate_memories_callback(callback_context: CallbackContext):
    """Callback after each turn to store session memories in Memory Bank."""
    await callback_context.add_session_to_memory()
    return None


code_executor = AgentEngineSandboxCodeExecutor(
    agent_engine_resource_name=AGENT_ENGINE_RESOURCE_NAME,
)

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    code_executor=code_executor,
    tools=[
        PreloadMemoryTool(),
        roll_dice,
        fetch_random_magic_item,
        lookup_dnd_rules,
        consult_herbal_docs,
        generate_fantasy_item_image,
        generate_fantasy_item_video,
        get_quests,
        create_or_update_quest,
    ],
    after_model_callback=a2ui_callback,
    after_agent_callback=generate_memories_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
