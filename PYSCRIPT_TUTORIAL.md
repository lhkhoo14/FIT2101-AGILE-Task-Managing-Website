# Getting Started with PyScript

This project uses **PyScript** to run Python directly in the browser for client-side form validation and logic. Follow the guide below to set up and run the application locally.

## Prerequisites

To run this project, you need a local web server.

* **VS Code Option (Recommended):** Install the [Live Server](https://marketplace.visualstudio.com/items?itemName=ritwickdey.LiveServer) extension.
* **Python Option:** Use Python's built-in HTTP server from your terminal, by the command:

        >> python3 -m http.server

## PyScript HTML Configuration

Include the PyScript CSS and JS core bundles in the <head> of your HTML files, and link settings.json in your `<script type="py">` tag:

```HTML
<!DOCTYPE html>
<html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Login</title>

        <!-- PyScript Core CDN -->
        <link 
            rel="stylesheet" 
            href="[https://pyscript.net/releases/2026.7.3/core.css](https://pyscript.net/releases/2026.7.3/core.css)"
        >
        <script 
            type="module" 
            src="[https://pyscript.net/releases/2026.7.3/core.js](https://pyscript.net/releases/2026.7.3/core.js)">
        </script>

        <link rel="stylesheet" href="../styles/auth.css">
    </head>
    <body>

        <!-- Your HTML Form Here -->

        <!-- PyScript Execution Tag -->
        <script 
            type="py" 
            config="../../settings.json" 
            src="../backend/login.py">
        </script>
    </body>
</html>
```

## Virtual File System Mapping (`settings.json`)
`settings.json` mounts your local Python backend files into Pyodide's virtual browser filesystem so imports work seamlessly:

```JSON
{
  "files": {
    "./src/backend/auth.py": "./auth.py",
    "./src/backend/login.py": "./login.py",
    "./src/backend/signup.py": "./signup.py",
    "./src/backend/models/user.py": "./models/user.py"
  }
}
```

## Running the Project Locally

The login page needs both the static frontend and the FastAPI backend running.
Run these commands from the repository root. Create a virtual environment if
you do not already have one:

```powershell
python -m venv .venv
```

Install the backend dependencies using the virtual environment's Python:

```powershell
.\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
```

Start the API in one terminal (no activation required):

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir server --reload --host 127.0.0.1 --port 8000

    ```
3. In a second terminal, start the frontend using Option A or Option B below.
   Do not use port 8000 for the frontend; that port belongs to the API.

### Option A: Using VS Code Live Server

1. Open the project root folder in VS Code.

2. Right-click `index.html` in the file directory.

3. Click Open with [Live Server](https://marketplace.visualstudio.com/items?itemName=ritwickdey.LiveServer) (in the bottom right corner, only if [Live Server](https://marketplace.visualstudio.com/items?itemName=ritwickdey.LiveServer) is installed).

### Option B: Using Python Terminal

1. Open your terminal in the root folder of the project.

2. Run:
    ```Bash
    python -m http.server 5500
    ```

3. Open your browser and navigate to:
    http://localhost:5500/src/views/login.html
