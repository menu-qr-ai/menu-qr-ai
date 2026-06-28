def get_available_plans() -> list[dict]:
    return [
        {"id": "free", "name": "Free", "monthly_price": 0, "limits": {"restaurants": 1, "ai_requests": 25}},
        {"id": "pro", "name": "Pro", "monthly_price": 29, "limits": {"restaurants": 3, "ai_requests": 1000}},
        {"id": "business", "name": "Business", "monthly_price": 79, "limits": {"restaurants": 10, "ai_requests": 5000}},
    ]
