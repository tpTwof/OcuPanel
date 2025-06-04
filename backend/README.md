## 📦 Setup with Poetry

### 1. Install Poetry (if you haven't):
Follow instruction here: https://python-poetry.org/docs/#installing-with-pipx

Verify it works:

```bash
poetry --version
```

---

### 2. Install Dependencies

```bash
poetry install
```

---

## 🚀 Running the Server
Make sure to setup .env (follow .env_sample for more details)
Run the local server directly via `main.py`:

```bash
poetry run python main.py
```

---

## 🧪 Detail docs for API

Open Swagger UI:

```
http://127.0.0.1:8000/docs
```

Open ReDoc:

```
http://127.0.0.1:8000/redoc
```

---

## 📤 Example API Usage

### Generate Report Endpoint

**POST** `/api/generate-report`  
Content‑Type: `multipart/form-data`

Form fields:

| Field | Type | Description |
|-------|------|-------------|
| `file` | File | Image file (.jpg/.png) |
| `note` | Text | Clinical Note (optional) |

```bash
curl -X POST http://localhost:8000/api/generate-report/   -F "file=@example.jpg"   -F "note=<optional note>" -o data/result.pdf
```
---

### Chat Endpoint

**POST** `/api/chat`
```bash
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"user_uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "message": "hello"'
  ```

Returns a reply to user's message.

---

### Generate Report Endpoint (JSON with different components of the report)

**POST** `/api/generate-report-content/`  
Content‑Type: `multipart/form-data`

Form fields:

| Field | Type | Description |
|-------|------|-------------|
| `file` | File | Image file (.jpg/.png) |
| `note` | Text | Clinical Note (optional) |
| `user_uuid` | Text | UUID for user (to use personalized info) |

```bash
curl -X POST http://localhost:8000/api/generate-report-content/   -F "file=@example.jpg"   -F "note=<optional note>"
```
Output:
```json
{
    "summary": <Synthesis report of all experts>,
    "cup_to_disc_ratio": <cup-to-disc ratio using segmented image>,
    "img_name": <name of the file to be used to access RGB segmented image>
}
```
---
### Get report's image
**GET** `api/get-report-image/{img_name}`
```bash
curl -X POST http://localhost:8000/get-report-image/{img_name}``
```
img_name to be used here is the img_name return from the output of ```api/generate-report-content/```. This API endpoint will then return the corresponding image using this name.