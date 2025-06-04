## Frontend
Before running the frontend, make sure that you have set up the backend and are running it with 
```bash
poetry run python main.py
```

### 1. Install npm
Follow the instructions here: https://nodejs.org/en/download

### 2. Install packages
```bash
npm install
```

### 3. Generate bundle.js
To use packages in the browser, we use browserify to add package support. Run this command whenever you make changes to `script.js`
```bash
browserify script.js -o bundle.js
```

### 4. Run frontend
The html file can be run in a browser or server to host. If using VSCode, the easiest way is to download the live server extension, and then right click on the html file to run with live server. If the backend is running, the requests will be made. 