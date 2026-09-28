import re
import asyncio
from pyscript import web  # type: ignore

def validate_email(email: str) -> tuple[bool, str]:
    """Validates email format using regex."""
    email = email.strip()
    if not email:
        return False, "Email address is required."
    
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    if not re.match(pattern, email):
        return False, "Please enter a valid email address."
    
    return True, ""

def validate_password(password: str, min_length: int = 8) -> tuple[bool, str]:
    """Validates password strength requirements."""
    if not password:
        return False, "Password is required."
    if len(password) < min_length:
        return False, f"Password must be at least {min_length} characters long."
    return True, ""

def get_dom_element(field_id: str):
    """Safely retrieves element by ensuring '#' selector prefix."""
    selector = f"#{str(field_id).lstrip('#')}"
    try:
        return web.page[selector]
    except Exception:
        return None

def show_feedback(field_id: str, message: str):
    input_elem = get_dom_element(field_id)
    error_elem = get_dom_element(f"{field_id}-error")

    if input_elem is not None:
        if "is-invalid" not in input_elem.classes:
            input_elem.classes.add("is-invalid")

    if error_elem is not None:
        error_elem.innerText = message
        if "show" not in error_elem.classes:
            error_elem.classes.add("show")

def clear_errors(field_ids: list[str]):
    for field_id in field_ids:
        input_elem = get_dom_element(field_id)
        error_elem = get_dom_element(f"{field_id}-error")

        # SAFELY remove classes only if they exist
        if input_elem is not None and "is-invalid" in input_elem.classes:
            input_elem.classes.remove("is-invalid")

        if error_elem is not None:
            error_elem.innerText = ""
            if "show" in error_elem.classes:
                error_elem.classes.remove("show")

async def show_snackbar(message: str, duration: float = 2.5):
    print("[Debug] 1. Entering show_snackbar")
    snackbar = get_dom_element("snackbar")
    
    if snackbar is not None:
        print("[Debug] 2. Displaying snackbar UI")
        snackbar.innerText = message
        snackbar.classes.add("show")
        
        print(f"[Debug] 3. Starting asyncio.sleep({duration})...")
        await asyncio.sleep(duration)
        print("[Debug] 4. Finished asyncio.sleep, hiding snackbar")
        
        snackbar.classes.remove("show")

def toggle_password_mask(input_id: str, eye_id: str, eye_off_id: str):
    password_input = get_dom_element(input_id)
    eye_icon = get_dom_element(eye_id)
    eye_off_icon = get_dom_element(eye_off_id)

    if not password_input:
        return

    if password_input.type == "password":
        password_input.type = "text"
        if eye_icon and "hidden" not in eye_icon.classes:
            eye_icon.classes.add("hidden")
        if eye_off_icon and "hidden" in eye_off_icon.classes:
            eye_off_icon.classes.remove("hidden")
    else:
        password_input.type = "password"
        if eye_icon and "hidden" in eye_icon.classes:
            eye_icon.classes.remove("hidden")
        if eye_off_icon and "hidden" not in eye_off_icon.classes:
            eye_off_icon.classes.add("hidden")