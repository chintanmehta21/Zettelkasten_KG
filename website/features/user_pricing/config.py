"""Editable pricing source of truth for the user pricing module.

All amounts are integer paise. Edit this file to change prices, quotas,
recommended products, or launch/list pricing. Frontend displays and backend
payment creation must derive from this config through catalog helpers.
"""

from __future__ import annotations

PRICING_CONFIG: dict = {
    "currency": "INR",
    "launch_pricing_enabled": True,
    "meters": {
        "zettel": {"label": "Zettels"},
        "kasten": {"label": "Kastens"},
        "rag_question": {"label": "RAG questions"},
    },
    "plans": {
        "free": {
            "id": "free",
            "name": "Free",
            "description": "A starter allowance for trying the knowledge workflow.",
            "quotas": {
                "zettel": {"daily": 2, "weekly": 10, "monthly": 30},
                "kasten": {"total": 1},
                "rag_question": {"monthly": 30},
            },
            "periods": {
                "monthly": {
                    "id": "free_monthly",
                    "label": "Monthly",
                    "months": 1,
                    "list_amount": 0,
                    "launch_amount": 0,
                }
            },
        },
        "basic": {
            "id": "basic",
            "name": "Basic",
            "description": "More daily capture room with a practical Kasten workspace.",
            "quotas": {
                "zettel": {"daily": 5, "weekly": 30, "monthly": 50},
                "kasten": {"total": 5},
                "rag_question": {"monthly": 100},
            },
            "periods": {
                "monthly": {
                    "id": "basic_monthly",
                    "label": "Monthly",
                    "months": 1,
                    "list_amount": 29900,
                    "launch_amount": 14900,
                },
                "quarterly": {
                    "id": "basic_quarterly",
                    "label": "Quarterly",
                    "months": 3,
                    "list_amount": 84900,
                    "launch_amount": 39900,
                },
                "yearly": {
                    "id": "basic_yearly",
                    "label": "Yearly",
                    "months": 12,
                    "list_amount": 299900,
                    "launch_amount": 149900,
                },
            },
        },
        "max": {
            "id": "max",
            "name": "Max",
            "description": "Higher capture and question limits for heavy personal research.",
            "quotas": {
                "zettel": {"daily": 30, "weekly": 100, "monthly": 200},
                "kasten": {"weekly": 5, "total": 50},
                "rag_question": {"monthly": 500},
            },
            "periods": {
                "monthly": {
                    "id": "max_monthly",
                    "label": "Monthly",
                    "months": 1,
                    "list_amount": 49900,
                    "launch_amount": 34900,
                },
                "quarterly": {
                    "id": "max_quarterly",
                    "label": "Quarterly",
                    "months": 3,
                    "list_amount": 144900,
                    "launch_amount": 99900,
                },
                "yearly": {
                    "id": "max_yearly",
                    "label": "Yearly",
                    "months": 12,
                    "list_amount": 499900,
                    "launch_amount": 349900,
                },
            },
        },
    },
    "packs": {
        "zettel": [
            {"id": "zettel_1", "meter": "zettel", "name": "1 Zettel", "quantity": 1, "list_amount": 2500, "launch_amount": 1500},
            {"id": "zettel_5", "meter": "zettel", "name": "5 Zettels", "quantity": 5, "list_amount": 9900, "launch_amount": 6900},
            {"id": "zettel_10", "meter": "zettel", "name": "10 Zettels", "quantity": 10, "list_amount": 17900, "launch_amount": 9900},
            {"id": "zettel_20", "meter": "zettel", "name": "20 Zettels", "quantity": 20, "list_amount": 32900, "launch_amount": 16900},
            {"id": "zettel_30", "meter": "zettel", "name": "30 Zettels", "quantity": 30, "list_amount": 50800, "launch_amount": 26800},
            {"id": "zettel_40", "meter": "zettel", "name": "40 Zettels", "quantity": 40, "list_amount": 65800, "launch_amount": 33800},
            {"id": "zettel_50", "meter": "zettel", "name": "50 Zettels", "quantity": 50, "list_amount": 83700, "launch_amount": 43700},
        ],
        "kasten": [
            {"id": "kasten_1", "meter": "kasten", "name": "1 Kasten", "quantity": 1, "list_amount": 12900, "launch_amount": 6900},
            {"id": "kasten_5", "meter": "kasten", "name": "5 Kastens", "quantity": 5, "list_amount": 49900, "launch_amount": 29900},
            {"id": "kasten_10", "meter": "kasten", "name": "10 Kastens", "quantity": 10, "list_amount": 89900, "launch_amount": 49900},
            {"id": "kasten_20", "meter": "kasten", "name": "20 Kastens", "quantity": 20, "list_amount": 159900, "launch_amount": 89900},
            {"id": "kasten_30", "meter": "kasten", "name": "30 Kastens", "quantity": 30, "list_amount": 249800, "launch_amount": 139800},
            {"id": "kasten_40", "meter": "kasten", "name": "40 Kastens", "quantity": 40, "list_amount": 319800, "launch_amount": 179800},
            {"id": "kasten_50", "meter": "kasten", "name": "50 Kastens", "quantity": 50, "list_amount": 409700, "launch_amount": 229700},
        ],
        "question": [
            {"id": "questions_50", "meter": "rag_question", "name": "50 Questions", "quantity": 50, "list_amount": 7500, "launch_amount": 4000},
            {"id": "questions_100", "meter": "rag_question", "name": "100 Questions", "quantity": 100, "list_amount": 14900, "launch_amount": 7900},
            {"id": "questions_150", "meter": "rag_question", "name": "150 Questions", "quantity": 150, "list_amount": 22400, "launch_amount": 11900},
            {"id": "questions_200", "meter": "rag_question", "name": "200 Questions", "quantity": 200, "list_amount": 29800, "launch_amount": 15800},
            {"id": "questions_250", "meter": "rag_question", "name": "250 Questions", "quantity": 250, "list_amount": 37300, "launch_amount": 19800},
            {"id": "questions_300", "meter": "rag_question", "name": "300 Questions", "quantity": 300, "list_amount": 44700, "launch_amount": 23700},
            {"id": "questions_350", "meter": "rag_question", "name": "350 Questions", "quantity": 350, "list_amount": 49900, "launch_amount": 24900},
            {"id": "questions_500", "meter": "rag_question", "name": "500 Questions", "quantity": 500, "list_amount": 49900, "launch_amount": 24900},
        ],
    },
    "custom_slider_values": {
        "zettel": [1, 5, 10, 20, 30, 40, 50],
        "kasten": [1, 5, 10, 20, 30, 40, 50],
        "question": [50, 100, 150, 200, 250, 300, 350],
    },
    "recommendations": {
        "zettel": ["zettel_10", "basic_monthly", "max_monthly"],
        "kasten": ["kasten_5", "max_monthly", "basic_monthly"],
        "rag_question": ["questions_500", "max_monthly", "basic_monthly"],
    },
}
