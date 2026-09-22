from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-01-f419067f0d55"


def seed_firestore():
    print(f"Initializing Firestore client for project: {PROJECT_ID}")
    db = firestore.Client(project=PROJECT_ID, database="(default)")

    quests_ref = db.collection("quests")

    initial_quests = [
        {
            "id": "quest_001",
            "title": "The Stolen Signet of Lord Valerius",
            "status": "In Progress",
            "difficulty": "Medium",
            "reward_gold": 150,
            "location": "Porthaven - Laughing Dragon Tavern",
            "description": "Retrieve the ancestral signet ring stolen by the notorious cutpurse known as 'The Whisker'.",
            "assigned_to": "Eldrin",
        },
        {
            "id": "quest_002",
            "title": "Clear the Whispering Catacombs",
            "status": "Available",
            "difficulty": "Hard",
            "reward_gold": 400,
            "location": "Porthaven - Eastern Cemetery",
            "description": "Locals report strange chanting and skeletal wanderers rising from the catacombs at midnight.",
            "assigned_to": None,
        },
        {
            "id": "quest_003",
            "title": "Escort the Alchemist's Caravan",
            "status": "Available",
            "difficulty": "Easy",
            "reward_gold": 80,
            "location": "Trade Road to Oakhaven",
            "description": "Protect Master Corvus and his volatile potion crates from goblin highwaymen.",
            "assigned_to": None,
        },
    ]

    print("Seeding quests collection...")
    for quest in initial_quests:
        doc_ref = quests_ref.document(quest["id"])
        doc_ref.set(quest)
        print(f"  - Added quest: {quest['id']} - {quest['title']}")

    print("Firestore seeding complete!")


if __name__ == "__main__":
    seed_firestore()
