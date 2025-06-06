# MedChat

> Philip Liu, Sparsh Bansal, Jimmy Dinh, Aditya Pawar, Ramani Satishkumar, Shail Desai, Neeraj Gupta, Xin Wang, Shu Hu  


A modular framework that uses modern vision back-ends with **role-specialised LLM agents** to draft glaucoma diagnostic reports from retinal fundus images. The core idea is for each agent to focus on a narrow clinical role, while a *Director* agent synthesises their opinions into a concise, clinically-grounded report.

---
## Method Overview

1. **Vision Pre-processing**  
   * **Classifier (SwinV2)** → glaucoma probability *p* (binned into “no glaucoma / possible glaucoma / likely glaucoma / glaucoma detected”).  
   * **Segmentor (SegFormer)** → optic-cup & disc masks → cup-to-disc ratio (CDR).

2. **Core Prompt**  
   Natural-language sentences summarise *p* and CDR, optionally appended with clinician notes.

3. **Role Generation**  
   A meta-prompt asks GPT-4.1 to list relevant clinical roles (e.g., Ophthalmologist, Optometrist, Pharmacist).

4. **Role-Specialised Sub-Reports**  
   Each role gets the core prompt plus narrow instructions and writes a focused sub-report.

5. **Director Synthesis**  
   Another GPT-4.1 instance combines all sub-reports, resolves minor conflicts, and produces one clean diagnostic report.

6. **Output & Interface**  
   The final report, probability, CDR, and sub-reports are returned to the client (e.g., MedChat front-end) for interactive Q&A and PDF export.
---

## ✨ Key Contributions
| # | Contribution | Why it matters |
|---|--------------|----------------|
| 1 | **Multi-agent reasoning**: Ophthalmologist, Optometrist, Pharmacist, … plus a Director agent | Reduces hallucinations and reflects real-world collaboration |
| 2 | **Tight CAD ⇄ LLM loop**: SwinV2 classifier (glaucoma probability) + SegFormer segmentor (optic-cup/optic-disc masks) | Keeps language output anchored to verifiable image features (e.g., CDR) |
| 3 | **MedChat interface** (browser-based) | Enables interactive Q&A and PDF report download for clinicians and learners – see `frontend/` for code; no external link included |
---

## Repository Layout
```
├── backend/              # Python API, multi-agent pipeline, model wrappers
│   ├── cad/              #  SwinV2 classifier & SegFormer segmentor
│   ├── agents/           #  Role prompts, Director logic
│   └── api.py            #  FastAPI / Flask endpoints
├── frontend/             #  Lightweight JS + HTML MedChat client
└── README.md
```
---
## MedChat Interface
The repo ships with a minimal **browser client** that:

1. uploads a fundus image + optional notes,  
2. streams sub-reports in real time,  
3. allows follow-up Q&A with full conversation memory, and  
4. exports the complete conversation as a styled PDF report.

---

## Citation
If you use this work, please cite:
```bibtex
@inproceedings{liu2025multiagent,
  title     = {Multi-Agent Diagnosis using Multimodal Large Language Models},
  author    = {Liu, Philip and Bansal, Sparsh and Dinh, Jimmy and Pawar, Aditya and Satishkumar, Ramani and Gupta, Neeraj and Wang, Xin and Hu, Shu},
  booktitle = {IEEE Int'l Conf. on Multimedia Information Processing and Retrieval (MIPR)},
  year      = {2025}
}
```

---

## License
This project is released under the **MIT License** (see `LICENSE`).

---

## Contact
For questions or collaboration requests, please open an issue or email (m2lab.purdue@gmail.com). 
