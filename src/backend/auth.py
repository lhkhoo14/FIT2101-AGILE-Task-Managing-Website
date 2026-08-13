import re
from pyscript import web


def validate_email(email: str) -> tuple[bool, str]:
    """Validates email format using regex."""
    email = email.strip()
    if not email:
        return False, "Email address is required."
    
    # Standard email pattern
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

def validate_signup_passwords(password: str, confirm_password: str) -> tuple[bool, str]:
    """Validates password strength and checks matching confirmation."""
    is_valid, msg = validate_password(password)
    if not is_valid:
        return False, msg
    
    if password != confirm_password:
        return False, "Passwords do not match."
    
    return True, ""

# --- SHOW ERROR ---
def show_feedback(field_id: str, message: str):
    input_element = web.page[field_id]
    error_element = web.page[f"{field_id}-error"]

    if input_element is not None:
        if input_element.value.strip() != "":
            input_element.classList.add("is-invalid")
        # Debug
        print(f"{field_id} invalid!")

    if error_element is not None:
        error_element.textContent = message
        error_element.classList.add("show")

# --- CLEAR ERRORS ---
def clear_errors(field_ids: list[str]):
    for field_id in field_ids:
        input_element = web.page[field_id]
        error_element = web.page[f"{field_id}-error"]

        if input_element is not None:
            input_element.classList.remove("is-invalid")

        if error_element is not None:
            error_element.textContent = ""
            error_element.classList.remove("show")

# --- SUCCESS SNACKBAR ---
def show_snackbar(message: str):
    snackbar = web.page["snackbar"]
    if snackbar is not None:
        snackbar.textContent = message
        snackbar.classList.add("show")