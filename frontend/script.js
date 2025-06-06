// Element References
const dropZoneImage = document.getElementById("dropZoneImage");
const imageInput = document.getElementById("imageInput");
const uploadsPreview = document.getElementById("uploadsPreview");
const sendToLLMBtn = document.getElementById("sendToLLM");
const clearHistoryBtn = document.getElementById("clearHistory");
const chatInput = document.getElementById("chatInput");
const sendChat = document.getElementById("sendChat");
const chatHistory = document.getElementById("chatHistory");
const clinicalNotesInput = document.getElementById("clinicalNotesInput");
const downloadPdfBtn = document.getElementById("downloadPdfBtn");
const downloadSection = document.getElementById("downloadSection");
const llmStatus = document.getElementById("llmStatus");
const imgPreview = document.getElementById("img");
const uploadPage = document.getElementById('uploadPage');
const mainPage = document.getElementById('main-content');
const overlay = document.getElementById('loading-overlay');
// const form = document.getElementById("test");

const aboutLink = document.getElementById('aboutLink');
// const modal = document.getElementById('aboutModal');
// const closeBtn = modal.querySelector('.close');

// Uploaded file tracking
let uploadedFiles = null;
let noteContent = null;

let id = crypto.randomUUID();

const showdown = require('showdown');
const converter = new showdown.Converter();

function showLoading() { overlay.style.display = 'flex'; }
function hideLoading() { overlay.style.display = 'none'; }

// Drag-and-Drop Handling
dropZoneImage.addEventListener("click", () => imageInput.click());

dropZoneImage.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZoneImage.style.backgroundColor = "#eee";
});

dropZoneImage.addEventListener("dragleave", () => {
  dropZoneImage.style.backgroundColor = "#f9f9f9";
});

dropZoneImage.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZoneImage.style.backgroundColor = "#f9f9f9";
  handleFileUpload(e.dataTransfer.files[0]);
});

imageInput.addEventListener("change", () => {
  handleFileUpload(imageInput.files[0]);
});

// File Upload
// Changing to a single file and TODO: let users remove file before upload
function handleFileUpload(file) {
  if (!file || !file.type.startsWith("image/")) {
    alert("Not a valid image")
    return;
  }
  uploadedFiles = file;

  const fileWrapper = document.createElement("div");
  fileWrapper.style.marginBottom = "10px";

  imgPreview.src = '';
  imgPreview.style.display = 'none';

  imgPreview.src = URL.createObjectURL(file);
  imgPreview.alt = file.name;
  imgPreview.style.borderRadius = "6px";
  imgPreview.style.padding = "5px";
  imgPreview.style.alignContent = "center";
  imgPreview.style.display = 'block';

  fileWrapper.appendChild(imgPreview);
  uploadsPreview.appendChild(fileWrapper);

  // imageInput.value = "";
}

// Send to LLM
sendToLLMBtn.addEventListener("click", () => {
  if (uploadedFiles == null) {
    alert("Please upload an image");
    return;
  }

  showLoading();

  downloadSection.style.display = "none";

  console.log("Starting");
  console.log(id)

  const formData = new FormData();
  formData.append('file', uploadedFiles);
  formData.append('note', clinicalNotesInput.value.trim());
  formData.append('user_uuid', id);

  const response = fetch('http://127.0.0.1:8000/api/generate-report-content/', {
    method: "POST",
    body: formData
  })
  .then(response => {
    if (!response.ok) {
      // Handle HTTP error statuses (4xx or 5xx)
      return response.text().then(errorMessage => {
        throw new Error(`${response.status} - ${errorMessage}`);
      });
    }
    return response.json();
  })
  .then(info => {
    // const url = URL.createObjectURL(data);
    // sessionStorage.setItem('pdf', url);
    // console.log("Saved download link")

    console.log("does this run")

    console.log(info)

    hideLoading();

    downloadSection.style.display = "block";

    const imgGet = fetch(`http://127.0.0.1:8000/api/get-report-image/${info.img_name}`, {
      method: "GET"
    })
    .then(response => {
      if (!response.ok) {
      // Handle HTTP error statuses (4xx or 5xx)
      return response.text().then(errorMessage => {
        throw new Error(`${response.status} - ${errorMessage}`);
      });
    }
    return response.blob();
    })
    .then(data => {
      const url = URL.createObjectURL(data);

      const aiMsg = document.createElement("div");
      aiMsg.classList.add("ai-message");
      aiMsg.innerHTML = `
        <strong>AI:</strong>
        ${converter.makeHtml(info.summary)}
      `;
      chatHistory.appendChild(aiMsg);

      noteContent = clinicalNotesInput.value.trim();

      const img = document.createElement("img");
      img.src = url;
      img.classList.add("ai-image");
      aiMsg.appendChild(img);

    })
    .catch(error => {
      console.log(error)
      alert(error)
      hideLoading()
    });

    // uploadPage.style.display = "none";
    // mainPage.style.display = "block";
  })
  .catch(error => {
    console.log(error)
    alert(error);

    hideLoading()
  });
});

function sendMessage(msg) {
  var isScrolledToBottom = chatHistory.scrollHeight - chatHistory.clientHeight <= chatHistory.scrollTop + 1;
  // console.log(isScrolledToBottom)

  const userMsg = document.createElement("p");
  userMsg.innerHTML = `<strong>You:</strong> ${msg}`;
  chatHistory.appendChild(userMsg);
  chatInput.value = "";

  if (isScrolledToBottom) {
      chatHistory.scrollTop = chatHistory.scrollHeight - chatHistory.clientHeight;
  }

  const aiMsg = document.createElement("div");
  aiMsg.classList.add("ai-message");
  aiMsg.innerHTML = `
    <strong>AI:</strong> <span class="dots"></span>
  `;
  chatHistory.appendChild(aiMsg);

  const dots = aiMsg.querySelector(".dots");
  let count = 0;
  const interval = setInterval(() => {
    count = (count + 1) % 4;            // cycles 0–3
    dots.textContent = ".".repeat(count);
  }, 500);

  const request = {
    user_id: id,
    message: msg
  }

  console.log(id)

  console.log(JSON.stringify(request))

  const response = fetch('http://localhost:8000/api/chat/', {
    method: "POST",
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(request)
  })
  .then(response => {
    if (!response.ok) {
      // Handle HTTP error statuses (4xx or 5xx)
      return response.text().then(errorMessage => {
        throw new Error(`${response.status} - ${errorMessage}`);
      });
    }
    return response.json();
  })
  .then(data => {
    isScrolledToBottom = chatHistory.scrollHeight - chatHistory.clientHeight <= chatHistory.scrollTop + 1;

    console.log("Runs after data", isScrolledToBottom)

    clearInterval(interval)

    aiMsg.innerHTML = `
      <strong>AI:</strong>
      ${converter.makeHtml(data.response)}
    `;

    isScrolledToBottom = chatHistory.scrollHeight - chatHistory.clientHeight <= chatHistory.scrollTop + 1;

    console.log("after", isScrolledToBottom)

    if (isScrolledToBottom) {
      chatHistory.scrollTop = chatHistory.scrollHeight - chatHistory.clientHeight;
    } 
  })
  .catch(error => {
    console.log(error)
    alert(error);
    clearInterval(interval)

    aiMsg.innerHTML = `
      <strong>AI:</strong> Error Occurred. Please try again.
    `;
  });

  console.log(isScrolledToBottom)

  if (isScrolledToBottom) {
      chatHistory.scrollTop = chatHistory.scrollHeight - chatHistory.clientHeight;
  } 
}

function uuidv4() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'
    .replace(/[xy]/g, function (c) {
        const r = Math.random() * 16 | 0, 
            v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// Chat Interface
// TODO: Back button state listener
sendChat.addEventListener("click", () => {
  const msg = chatInput.value.trim();
  if (!msg) {
    alert("Please enter text before sending!")
    return
  };

  sendMessage(msg)
});

// So that enter sends chat request
chatInput.addEventListener("keypress", function(event) {
  if (event.key === "Enter") {
    event.preventDefault();
    const msg = chatInput.value.trim();
    if (!msg) {
      alert("Please enter text before sending!")
      return
    };

    sendMessage(msg);
  }
});

// Clear Chat
clearHistoryBtn.addEventListener("click", () => {
  chatHistory.innerHTML = "";
  uploadsPreview.innerHTML = "<h3>Uploaded Files</h3>";
  clinicalNotesInput.value = "";
  uploadedFiles = null;
  downloadSection.style.display = "none";
  llmStatus.style.display = "none";

  const request = {
    user_id: id,
    message: ""
  }

  const response = fetch('http://127.0.0.1:8000/api/chat/reset/', {
    method: "POST",
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(request)
  })
  .then(response => {
    if (!response.ok) {
      // Handle HTTP error statuses (4xx or 5xx)
      return response.text().then(errorMessage => {
        throw new Error(`${response.status} - ${errorMessage}`);
      });
    }
    return response.json();
  })
  .then(data => {
    console.log("Success:", data)
  })
  .catch(error => {
    console.log(error)
    alert(error);
  });

  id = crypto.randomUUID();
});

// Download Simulation
function downloadReportAsPDF() {
  showLoading();

  console.log("Starting");

  const formData = new FormData();
  formData.append('file', uploadedFiles);
  formData.append('note', noteContent);
  formData.append('user_uuid', id);

  const response = fetch('http://127.0.0.1:8000/api/generate-report/', {
    method: "POST",
    body: formData
  })
  .then(response => {
    if (!response.ok) {
      // Handle HTTP error statuses (4xx or 5xx)
      return response.text().then(errorMessage => {
        throw new Error(`${response.status} - ${errorMessage}`);
      });
    }
    return response.blob();
  })
  .then(data => {
    console.log(data)

    hideLoading();

    const a = document.createElement('a');
    a.href = URL.createObjectURL(data);
    a.download = "diagnostic_report.pdf";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(URL.createObjectURL(data));
  })
  .catch(error => {
    console.log(error)
    alert(error);
  });
}

// TODO: Generation report does not add LLM queries and answers
downloadPdfBtn.addEventListener("click", downloadReportAsPDF);

// aboutLink.onclick = e => {
//   e.preventDefault();
//   modal.style.display = 'flex';
// };
// closeBtn.onclick = () => modal.style.display = 'none';
// window.onclick = e => {
//   if (e.target === modal) modal.style.display = 'none';
// };

aboutLink.addEventListener("click", (e) => {
  e.preventDefault();
  document.getElementById("aboutModal").style.display = "block";
});

document.getElementById('closeAbout').onclick = (e) => {
  e.preventDefault();
  document.getElementById('aboutModal').style.display = 'none';
};