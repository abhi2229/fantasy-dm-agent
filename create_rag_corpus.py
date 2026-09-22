import vertexai
from vertexai.preview import rag
from vertexai.preview.rag.utils import resources as rr

PROJECT_ID = "qwiklabs-gcp-01-f419067f0d55"
LOCATION = "us-central1"
GCS_PATH = "gs://qwiklabs-gcp-01-f419067f0d55-rag-bucket/herbal/pg49513.txt"

PARSING_PROMPT = (
    "Extract the individual useful facts, herbs, remedies, and recipes described in this text. "
    "Ignore and omit all metadata, boilerplate, and publishing license headers/footers. "
    "Output clean, self-contained prose."
)

def create_rag_corpus():
    print(f"Initializing Vertex AI for project {PROJECT_ID} in {LOCATION}...")
    vertexai.init(project=PROJECT_ID, location=LOCATION)

    print("Switching RAG managed DB to serverless mode...")
    cfg = f"projects/{PROJECT_ID}/locations/{LOCATION}/ragEngineConfig"
    rag.update_rag_engine_config(
        rag_engine_config=rag.RagEngineConfig(
            name=cfg,
            rag_managed_db_config=rag.RagManagedDbConfig(mode=rr.Serverless()),
        )
    )

    print("Creating RAG corpus...")
    corpus = rag.create_corpus(
        display_name="herbal-complete-corpus",
        embedding_model_config=rag.EmbeddingModelConfig(
            publisher_model="publishers/google/models/text-embedding-005"
        ),
    )
    print("Corpus created:", corpus.name)

    print(f"Importing and indexing {GCS_PATH}...")
    resp = rag.import_files(
        corpus_name=corpus.name,
        paths=[GCS_PATH],
        transformation_config=rag.TransformationConfig(
            chunking_config=rag.ChunkingConfig(chunk_size=512, chunk_overlap=100)
        ),
        llm_parser=rag.LlmParserConfig(
            model_name="gemini-2.5-flash",
            custom_parsing_prompt=PARSING_PROMPT,
        ),
    )
    print(f"Import complete! Imported RAG files count: {resp.imported_rag_files_count}")
    return corpus.name

if __name__ == "__main__":
    create_rag_corpus()
