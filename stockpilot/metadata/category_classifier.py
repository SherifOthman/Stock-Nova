"""
StockNova AI — Stock Photography Category Classifier.
Provides strict, validated category mappings for:
1. Adobe Stock: Numeric IDs 1 to 21 (required by Adobe Contributor CSV upload).
2. Freepik: Formats (Photos, Vectors, PSDs) and algorithmic keyword taxonomy.
"""

from __future__ import annotations

import re
from typing import Any

# =====================================================================
# OFFICIAL ADOBE STOCK 21 NUMERIC CATEGORIES
# =====================================================================
ADOBE_CATEGORIES: dict[int, str] = {
    1: "Animals",
    2: "Buildings and Architecture",
    3: "Business",
    4: "Drinks",
    5: "The Environment",
    6: "States of Mind",
    7: "Food",
    8: "Graphic Resources",
    9: "Hobbies and Leisure",
    10: "Industry",
    11: "Landscapes",
    12: "Lifestyle",
    13: "People",
    14: "Plants and Flowers",
    15: "Culture and Religion",
    16: "Science",
    17: "Social Issues",
    18: "Sports",
    19: "Technology",
    20: "Transport",
    21: "Travel",
}

# Reverse mapping: lowercase string -> category ID
ADOBE_NAME_TO_ID: dict[str, int] = {
    name.lower(): cat_id for cat_id, name in ADOBE_CATEGORIES.items()
}

# Synonyms and aliases mapping directly to Adobe Category IDs
ADOBE_SYNONYMS: dict[str, int] = {
    # 1: Animals
    "animal": 1, "animals": 1, "pet": 1, "pets": 1, "dog": 1, "cat": 1, "wildlife": 1, "fauna": 1,
    # 2: Buildings and Architecture
    "architecture": 2, "architectural": 2, "building": 2, "buildings": 2, "interior": 2, "interiors": 2,
    "minimalist_interiors": 2, "house": 2, "facade": 2, "skyscraper": 2, "urban_architecture": 2,
    # 3: Business
    "business": 3, "business_objects": 3, "corporate": 3, "finance": 3, "investment": 3, "office": 3,
    "money": 3, "banking": 3, "commerce": 3, "trading": 3, "economy": 3,
    # 4: Drinks
    "drinks": 4, "drink": 4, "beverage": 4, "beverages": 4, "coffee": 4, "tea": 4, "wine": 4, "cocktail": 4,
    "smoothie": 4, "smoothies": 4, "juice": 4,
    # 5: The Environment
    "environment": 5, "the environment": 5, "clean_energy": 5, "ecology": 5, "sustainability": 5,
    "green_energy": 5, "solar": 5, "eco": 5, "renewable": 5,
    # 6: States of Mind
    "states of mind": 6, "states_of_mind": 6, "mindfulness": 6, "mental_health": 6, "emotion": 6,
    "concept": 6, "success": 6, "meditation": 6, "zen": 6,
    # 7: Food
    "food": 7, "food_and_drink": 7, "culinary": 7, "dish": 7, "meal": 7, "cooking": 7, "baking": 7,
    "dessert": 7, "fruit": 7, "vegetable": 7, "breakfast": 7, "gourmet": 7,
    # 8: Graphic Resources
    "graphic resources": 8, "graphic_resources": 8, "textures_and_backgrounds": 8, "texture": 8,
    "textures": 8, "background": 8, "backgrounds": 8, "abstract_3d": 8, "3d_render": 8, "mockup": 8,
    "mockups": 8, "pattern": 8, "patterns": 8, "vector_icons": 8, "wallpaper": 8,
    # 9: Hobbies and Leisure
    "hobbies and leisure": 9, "hobbies_and_leisure": 9, "hobbies": 9, "leisure": 9, "gaming": 9,
    "crafts": 9, "music": 9, "reading": 9, "diy": 9,
    # 10: Industry
    "industry": 10, "industrial": 10, "industrial_and_science": 10, "manufacturing": 10, "factory": 10,
    "machinery": 10, "construction": 10, "engineering": 10,
    # 11: Landscapes
    "landscapes": 11, "landscape": 11, "nature_and_landscapes": 11, "mountains": 11, "ocean": 11,
    "beach": 11, "nature": 11, "forest": 11, "sunset": 11, "sea": 11,
    # 12: Lifestyle
    "lifestyle": 12, "wellness": 12, "daily_life": 12, "routine": 12, "fashion": 12, "beauty": 12,
    # 13: People
    "people": 13, "portrait": 13, "portraits": 13, "person": 13, "crowd": 13, "diversity": 13, "human": 13,
    # 14: Plants and Flowers
    "plants and flowers": 14, "plants_and_flowers": 14, "plants": 14, "plant": 14, "flowers": 14,
    "flower": 14, "botanical": 14, "floral": 14, "succulent": 14, "garden": 14,
    # 15: Culture and Religion
    "culture and religion": 15, "culture_and_religion": 15, "culture": 15, "religion": 15, "tradition": 15,
    "holiday": 15, "ramadan": 15, "celebration": 15, "heritage": 15,
    # 16: Science
    "science": 16, "laboratory": 16, "medicine": 16, "medical": 16, "healthcare": 16, "genetics": 16,
    "biology": 16, "chemistry": 16, "doctor": 16, "hospital": 16,
    # 17: Social Issues
    "social issues": 17, "social_issues": 17, "community": 17, "equality": 17, "charity": 17, "volunteering": 17,
    # 18: Sports
    "sports": 18, "sport": 18, "fitness": 18, "gym": 18, "workout": 18, "training": 18, "running": 18, "yoga": 18,
    # 19: Technology
    "technology": 19, "tech": 19, "ai": 19, "artificial_intelligence": 19, "cyber": 19, "robotics": 19,
    "computer": 19, "data": 19, "software": 19, "smart_devices": 19, "internet": 19,
    # 20: Transport
    "transport": 20, "transportation": 20, "vehicles": 20, "vehicle": 20, "car": 20, "cars": 20,
    "aviation": 20, "airplane": 20, "train": 20, "automotive": 20, "logistics": 20,
    # 21: Travel
    "travel": 21, "tourism": 21, "vacation": 21, "destination": 21, "trip": 21, "landmark": 21, "passport": 21
}

# Keyword dictionaries for scoring when no explicit category is provided
CATEGORY_KEYWORD_WEIGHTS: dict[int, set[str]] = {
    1: {"animal", "animals", "pet", "pets", "dog", "cat", "wildlife", "safari", "bird", "birds", "fish", "horse", "mammal", "puppy", "kitten", "fauna", "creature", "insect"},
    2: {"building", "buildings", "architecture", "architectural", "facade", "interior", "interiors", "exterior", "skyscraper", "house", "room", "apartment", "villa", "living room", "kitchen", "bedroom", "bathroom", "minimalist room", "urban", "monument", "bridge", "tower", "construction"},
    3: {"business", "corporate", "finance", "financial", "investment", "office", "worker", "meeting", "money", "banking", "bank", "currency", "stock market", "chart", "graph", "commerce", "contract", "consulting", "executive", "handshake", "analytics", "strategy", "boardroom", "coworking"},
    4: {"drink", "drinks", "beverage", "beverages", "coffee", "tea", "wine", "beer", "juice", "cocktail", "smoothie", "espresso", "latte", "cappuccino", "glass", "cup", "barista", "liquor", "bottle", "refreshment"},
    5: {"environment", "ecology", "sustainability", "solar", "wind turbine", "green energy", "clean energy", "recycling", "eco", "climate", "conservation", "nature conservation", "renewable", "earth"},
    6: {"mindfulness", "meditation", "stress", "mental health", "emotion", "happiness", "success", "relaxation", "zen", "idea", "thought", "contemplation", "joy", "mood", "feeling", "spiritual"},
    7: {"food", "dish", "dishes", "meal", "meals", "cuisine", "recipe", "cooking", "dessert", "fruit", "vegetable", "dinner", "lunch", "breakfast", "gourmet", "baking", "pastry", "culinary", "bowl", "snack", "dumpling", "dumplings", "steamer", "dim sum", "noodle", "noodles", "pasta", "pizza", "burger", "sandwich", "soup", "salad", "meat", "chicken", "rice", "sushi", "bread", "cake", "avocado"},
    8: {"background", "backgrounds", "texture", "textures", "pattern", "patterns", "3d render", "mockup", "mockups", "abstract", "wallpaper", "geometric", "overlay", "marble", "render", "3d illustration", "surface", "backdrop", "graphic", "isolated"},
    9: {"hobby", "hobbies", "leisure", "craft", "crafts", "diy", "painting", "reading", "music", "instrument", "guitar", "piano", "gaming", "game", "gardening", "knitting", "drawing"},
    10: {"industry", "industrial", "manufacturing", "factory", "machinery", "machine", "engineering", "warehouse", "production", "steel", "automation", "welding", "plant", "assembly"},
    11: {"landscape", "landscapes", "mountain", "mountains", "ocean", "beach", "forest", "desert", "sunset", "sunrise", "scenic", "valley", "coast", "lake", "nature vista", "sea", "sky", "horizon"},
    12: {"lifestyle", "wellness", "routine", "daily life", "fashion", "skincare", "beauty", "cosmetics", "healthy living", "comfort", "modern life", "home life", "relaxation"},
    13: {"people", "person", "portrait", "portraits", "human", "crowd", "smiling", "face", "man", "woman", "child", "diversity", "hands", "expression", "model", "couple", "family"},
    14: {"plant", "plants", "flower", "flowers", "botanical", "leaf", "leaves", "flora", "succulent", "garden", "blossom", "rose", "herbal", "indoor plant", "tree", "trees", "foliage"},
    15: {"culture", "religion", "heritage", "festival", "tradition", "traditional", "holiday", "celebration", "temple", "mosque", "church", "ramadan", "spiritual", "easter", "christmas"},
    16: {"science", "laboratory", "lab", "medicine", "medical", "doctor", "hospital", "healthcare", "dna", "microscope", "chemistry", "biology", "pharmaceutical", "clinic", "scientific", "research"},
    17: {"social issues", "community", "equality", "charity", "volunteering", "poverty", "diversity", "support", "donation", "human rights", "inclusion", "society"},
    18: {"sport", "sports", "fitness", "gym", "workout", "athlete", "running", "training", "exercise", "yoga", "football", "basketball", "marathon", "athletics", "swimming"},
    19: {"technology", "tech", "ai", "artificial intelligence", "robotics", "cyber", "cybersecurity", "digital", "data", "computer", "laptop", "server", "code", "coding", "software", "internet", "cloud", "robot", "drone", "smartphone"},
    20: {"transport", "transportation", "vehicle", "vehicles", "car", "cars", "automobile", "airplane", "plane", "aviation", "flight", "train", "traffic", "highway", "logistics", "road", "shipping"},
    21: {"travel", "tourism", "vacation", "destination", "trip", "tourist", "luggage", "passport", "suitcase", "sightseeing", "journey", "explore", "voyage", "holiday trip"}
}


class CategoryClassifier:
    """Classifies stock assets into official Adobe Stock 21 numeric categories."""

    @classmethod
    def get_adobe_category_id_and_name(
        cls,
        title: str = "",
        keywords: list[str] | str | None = None,
        explicit_category: str | int | None = None,
        concept: str = ""
    ) -> tuple[int, str]:
        """
        Returns (numeric_category_id, category_name) strictly conforming to Adobe Stock standards.
        Guarantees category_id is an integer 1..21.
        """
        # 1. Check if explicit_category is already an integer 1..21
        if explicit_category is not None:
            try:
                cat_int = int(str(explicit_category).strip())
                if cat_int in ADOBE_CATEGORIES:
                    return cat_int, ADOBE_CATEGORIES[cat_int]
            except (ValueError, TypeError):
                pass

        # 2. Check if explicit_category matches known synonyms
        if explicit_category:
            clean_cat = str(explicit_category).strip().lower().replace("-", "_").replace(" ", "_")
            if clean_cat in ADOBE_SYNONYMS:
                cat_id = ADOBE_SYNONYMS[clean_cat]
                return cat_id, ADOBE_CATEGORIES[cat_id]
            # Try spaces
            clean_cat_spaces = str(explicit_category).strip().lower()
            if clean_cat_spaces in ADOBE_NAME_TO_ID:
                cat_id = ADOBE_NAME_TO_ID[clean_cat_spaces]
                return cat_id, ADOBE_CATEGORIES[cat_id]

        # 3. Check concept string
        if concept:
            clean_concept = concept.strip().lower().replace("-", "_").replace(" ", "_")
            if clean_concept in ADOBE_SYNONYMS:
                cat_id = ADOBE_SYNONYMS[clean_concept]
                return cat_id, ADOBE_CATEGORIES[cat_id]

        # 4. Keyword and Title scoring across 21 categories
        tokens: set[str] = set()
        
        # Tokenize title
        if title:
            for word in re.findall(r'[a-zA-Z]{3,}', title.lower()):
                tokens.add(word)

        # Tokenize keywords
        if keywords:
            if isinstance(keywords, str):
                k_list = [k.strip().lower() for k in keywords.split(",") if k.strip()]
            else:
                k_list = [str(k).strip().lower() for k in keywords if str(k).strip()]
            for kw in k_list:
                for word in re.findall(r'[a-zA-Z]{3,}', kw):
                    tokens.add(word)

        # Score categories
        scores: dict[int, int] = {}
        for cat_id, kw_set in CATEGORY_KEYWORD_WEIGHTS.items():
            intersection = tokens.intersection(kw_set)
            if intersection:
                scores[cat_id] = len(intersection)

        if scores:
            # Pick highest score
            best_id = max(scores.items(), key=lambda x: x[1])[0]
            return best_id, ADOBE_CATEGORIES[best_id]

        # 5. Smart Default Fallback
        # If title contains 3d, mockup, background -> 8 (Graphic Resources)
        # If title contains food, drink -> 7 or 4
        # Else default to 8 (Graphic Resources) or 19 (Technology) which are high-volume stock categories
        return 8, ADOBE_CATEGORIES[8]
