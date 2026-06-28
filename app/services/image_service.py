from app.services.openai_service import openai_service


def build_description_prompt(dish_name: str, style: str = "modern restaurant") -> str:
    return f"Create an appetizing image prompt for {dish_name} in a {style} style."


def generate_dish_image_prompt(dish_name: str, style: str = "modern restaurant") -> dict:
    prompt = build_description_prompt(dish_name, style)
    return openai_service.json_completion(
        system="You create concise image generation prompts for restaurant dishes.",
        prompt=f'Return JSON with key "prompt" for this request: {prompt}',
    )
