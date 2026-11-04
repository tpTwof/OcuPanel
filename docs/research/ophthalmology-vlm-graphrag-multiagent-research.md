# Ophthalmology VLM + GraphRAG + Multi-Agent Research Report

**Date:** 2025-01  
**Scope:** Vision-Language Models for fundus image analysis, GraphRAG implementations for medical knowledge bases, Multi-Agent frameworks for medical AI, and integration architectures.

---

## 1. Vision-Language Models (VLMs) for Ophthalmology / Fundus Image Analysis

### 1.1 RetiZero — Knowledge-Rich VLM for Fundus Diseases

| Field | Details |
|-------|---------|
| **Paper** | "Enhancing Diagnostic Accuracy in Rare and Common Fundus Diseases with a Knowledge-Rich Vision-Language Model" ([arXiv:2406.09317](https://arxiv.org/abs/2406.09317)) |
| **Published** | Jun 2024 (revised Apr 2025); accepted at Nature Communications 2025 |
| **Architecture** | Vision-Language contrastive model (CLIP-style) pre-trained on 341,896 fundus image-text pairs covering 400+ diseases |
| **Supported Tasks** | Zero-shot disease recognition, image-to-image retrieval, AI-assisted clinical diagnosis, few-shot fine-tuning, cross-domain disease identification |
| **Open Source** | ✅ Yes — [GitHub: LooKing9218/RetiZero](https://github.com/LooKing9218/RetiZero) |
| **Benchmarks** | Zero-shot Top-5 accuracy: 0.843 (15 diseases), 0.756 (52 diseases). Image retrieval Top-5: 0.950 (15 diseases), 0.886 (52 diseases). Top-3 zero-shot surpasses average of 19 ophthalmologists from Singapore, China, and US |
| **Input** | Fundus photographs (color fundus photos) |
| **Special Considerations** | Requires GPU for inference; excels at rare disease identification; designed as a clinical decision support tool rather than standalone diagnostician |

**Key Strength:** Covers 400+ fundus diseases with knowledge-rich pretraining, making it the most comprehensive open-source fundus VLM available. Particularly strong for rare diseases where traditional classifiers fail.

---

### 1.2 VisionUnite — Ophthalmology VL Foundation Model with Clinical Knowledge

| Field | Details |
|-------|---------|
| **Paper** | "VisionUnite: A Vision-Language Foundation Model for Ophthalmology Enhanced with Clinical Knowledge" ([arXiv:2408.02865](https://arxiv.org/abs/2408.02865)) |
| **Published** | Aug 2024; accepted at IEEE TPAMI 2025 |
| **Architecture** | Vision-language foundation model enhanced with clinical knowledge; pre-trained on 1.24M image-text pairs, fine-tuned on MMFundus dataset (296,379 fundus image-text pairs + 889,137 simulated doctor-patient dialogues) |
| **Supported Tasks** | Open-ended multi-disease diagnosis, clinical explanation, patient interaction, educational aid for junior ophthalmologists |
| **Open Source** | ✅ Yes — [GitHub: HUANGLIZI/VisionUnite](https://github.com/HUANGLIZI/VisionUnite) |
| **Benchmarks** | Outperforms GPT-4V and Gemini Pro in ophthalmic diagnostics; diagnostic capabilities comparable to junior ophthalmologists |
| **Input** | Fundus photographs |
| **Special Considerations** | Strong conversational/dialogue capability via simulated doctor-patient dialogue training; suitable for patient-facing applications and education |

**Key Strength:** Best-in-class for conversational ophthalmic AI — can explain diagnoses, interact with patients, and serve as an educational tool. The dialogue component is unique among fundus VLMs.

---

### 1.3 RETFound — Retinal Foundation Model (Self-Supervised)

| Field | Details |
|-------|---------|
| **Paper** | "A foundation model for generalizable disease detection from retinal images" ([Nature 622, 156–163, 2023](https://www.nature.com/articles/s41586-023-06555-x)) |
| **Published** | Oct 2023 (Nature) |
| **Architecture** | ViT-Large (~307M params) pre-trained with Masked Autoencoding (MAE) on 1.6 million retinal images (CFP and OCT). Also supports DINOv2 and DINOv3 backbones |
| **Supported Tasks** | DR grading, glaucoma, AMD, diabetic macular edema, hypertensive retinopathy, cardiovascular risk prediction, systemic disease detection. Task-specific fine-tuning required |
| **Open Source** | ✅ Yes — [GitHub: rmaphoh/RETFound_MAE](https://github.com/rmaphoh/RETFound_MAE); Weights on [HuggingFace: YukunZhou](https://huggingface.co/YukunZhou) |
| **Benchmarks** | State-of-the-art on multiple public benchmarks (MESSIDOR-2, APTOS, REFUGE, etc.) after fine-tuning. Validated across diverse populations and imaging devices |
| **Input** | Color fundus photographs (CFP) and OCT scans |
| **Special Considerations** | Not a VLM per se — it's a vision-only foundation model requiring task-specific fine-tuning heads. No natural language interface. Excellent feature extractor for downstream classifiers. Supports CUDA 12+, PyTorch 2.3+. Colab notebook available for quick testing |

**Key Strength:** Most validated retinal foundation model with the largest pre-training corpus (1.6M images). Gold standard for feature extraction. Can be combined with an LLM to create a VLM pipeline.

---

### 1.4 MedDr — Diagnosis-Guided Medical Vision-Language Model

| Field | Details |
|-------|---------|
| **Paper** | "MedDr: Diagnosis-Guided Bootstrapping for Large-Scale Medical Vision-Language Learning" ([arXiv:2404.15127](https://arxiv.org/abs/2404.15127)) |
| **Published** | Apr 2024 |
| **Architecture** | Based on InternVL-Chat architecture; diagnosis-guided bootstrapping for large-scale medical VL learning. Tags include retinography, radiology, pathology, dermatology, endoscopy |
| **Supported Tasks** | Multi-modal medical diagnosis across specialties including retinography/fundus imaging, medical VQA, report generation |
| **Open Source** | ✅ Yes — [HuggingFace: Sunanhe/MedDr_0401](https://huggingface.co/Sunanhe/MedDr_0401); [GitHub: sunanhe/MedDr](https://github.com/sunanhe/meddr) |
| **Benchmarks** | Evaluated on multiple medical imaging benchmarks; generalist medical VL model |
| **Input** | Multiple medical image types including fundus/retinography, X-ray, CT, pathology slides |
| **Special Considerations** | Generalist medical model (not ophthalmology-specific); uses Transformers library with custom code; MIT license |

**Key Strength:** Broadest medical coverage among open-source VL models; includes retinography as a supported modality. Good choice when you need a single model for multiple medical imaging tasks beyond just fundus.

---

### 1.5 FLAIR — Foundation Language-Image Model of the Retina

| Field | Details |
|-------|---------|
| **Paper** | "A Foundation Language-Image Model of the Retina (FLAIR): Encoding Expert Knowledge in Text Supervision" ([Medical Image Analysis, Vol 99, 2025](https://www.sciencedirect.com/science/article/abs/pii/S1361841524002822)) |
| **Published** | Jan 2025 |
| **Architecture** | CLIP-style vision-language model that encodes expert ophthalmology knowledge directly into text supervision during pre-training |
| **Supported Tasks** | Zero-shot retinal disease classification, image-text retrieval, DR grading, glaucoma detection, AMD classification |
| **Open Source** | ⚠️ Limited — Paper published but GitHub/code availability unclear as of early 2025 |
| **Benchmarks** | Demonstrates improved zero-shot performance by encoding expert knowledge vs. generic CLIP |
| **Input** | Fundus photographs |
| **Special Considerations** | Novel approach of using structured expert knowledge as text supervision; may require contacting authors for access |

**Key Strength:** Unique methodology of encoding expert ophthalmology knowledge into the text encoder, improving alignment between visual features and clinical terminology.

---

### 1.6 Ophtha-LLaMA2 — Ophthalmology-Specific LLM

| Field | Details |
|-------|---------|
| **Paper** | "Ophtha-LLaMA2: A Large Language Model for Ophthalmology" ([arXiv:2312.04906](https://arxiv.org/abs/2312.04906)) |
| **Published** | Dec 2023 |
| **Architecture** | Fine-tuned LLaMA2 on three modalities of ophthalmic report data |
| **Supported Tasks** | Ophthalmic disease diagnosis from reports/text (NOT direct image analysis); clinical decision support |
| **Open Source** | ⚠️ Code/paper available but model weights availability unclear |
| **Benchmarks** | Significantly outperforms other LLMs on ophthalmic diagnosis tasks even with smaller fine-tuning dataset |
| **Input** | Ophthalmic reports/text (three modalities) — NOT direct fundus images |
| **Special Considerations** | This is a TEXT-ONLY LLM for ophthalmology, not a VLM. Useful as the language component in a VLM pipeline or for processing ophthalmic reports |

**Key Strength:** Best specialized ophthalmology text understanding. Can serve as the LLM backbone when combined with a vision encoder like RETFound for a complete VLM system.

---

### 1.7 EyeGPT — Ophthalmic Assistant with LLMs

| Field | Details |
|-------|---------|
| **Paper** | "EyeGPT: Ophthalmic Assistant with Large Language Models" (Chen, Zhao et al., 2024) ([Semantic Scholar](https://www.semanticscholar.org/paper/EyeGPT%3A-Ophthalmic-Assistant-with-Large-Language-Chen-Zhao/547ce91f3b7390c8887f91df8a7f97217fff7bf2)) |
| **Published** | 2024 (presented at Asia-Pacific Teleophthalmology Society) |
| **Architecture** | LLM-based ophthalmic assistant (specific base model not confirmed in available sources) |
| **Supported Tasks** | Ophthalmic clinical assistance, question answering, potentially multimodal |
| **Open Source** | ❌ Not confirmed as open-source |
| **Benchmarks** | Limited public benchmark data available |
| **Input** | Likely text-based ophthalmic queries; multimodal capability unconfirmed |
| **Special Considerations** | Early-stage project; limited public documentation |

---

### 1.8 General-Purpose Medical VLMs Applicable to Fundus Images

#### LLaVA-Med v1.5
| Field | Details |
|-------|---------|
| **Architecture** | LLaVA architecture adapted for medical domain; Vicuna/LLaMA base + CLIP vision encoder + medical instruction tuning |
| **Fundus Applicability** | ⚠️ Limited — trained primarily on radiology, pathology, and biomedical literature. Fundus/retinal images are underrepresented in training data |
| **Open Source** | ✅ [GitHub: microsoft/LLaVA-Med](https://github.com/microsoft/LLaVA-Med); HuggingFace available |
| **Benchmarks** | Strong on medical VQA benchmarks; weak on fundus-specific tasks without fine-tuning |
| **Recommendation** | Use only as a baseline comparison or if you plan significant ophthalmology fine-tuning |

#### Med-PaLM-M
| Field | Details |
|-------|---------|
| **Architecture** | Google's multimodal medical AI; PaLM-E base + medical instruction tuning; supports X-ray, CT, pathology, dermatology, and some ophthalmology |
| **Fundus Applicability** | ⚠️ Moderate — has some retinal/fundus capability but not its primary focus |
| **Open Source** | ❌ Not open-source (API access only through Google Cloud) |
| **Benchmarks** | State-of-the-art on general medical multimodal benchmarks; first comprehensive generalist biomedical AI system |
| **Recommendation** | Use as an upper-bound benchmark via API; not practical for self-hosted deployment |

#### BiomedCLIP
| Field | Details |
|-------|---------|
| **Architecture** | CLIP-style model pre-trained on PubMed Central biomedical literature with image-text pairs |
| **Fundus Applicability** | ⚠️ Moderate — parameter-efficient fine-tuning (LoRA/adapter) has shown promise for DR detection ([Stanford CS231N 2025 report](https://cs231n.stanford.edu/2025/papers/text_file_840579440-CS231N_Final_Report_2025%20(1).pdf)) |
| **Open Source** | ✅ [HuggingFace: microsoft/BiomedCLIP](https://huggingface.co/microsoft/BiomedCLIP) |
| **Benchmarks** | Competitive on biomedical image classification after fine-tuning; DR detection achievable with PEFT |
| **Recommendation** | Good lightweight option for DR screening with fine-tuning; less capable for multi-disease diagnosis |

---

### 1.9 Chinese Ophthalmology VLMs

Based on the research, several Chinese institutions have produced relevant models:

- **VisionUnite** (see §1.2) — Authors affiliated with Chinese institutions (Sun Yat-sen University area based on author names Xiulan Zhang, Fei Li who are prominent SUNYAT-SEN ophthalmology researchers)
- **RetiZero** (see §1.1) — Multi-institutional collaboration including Chinese researchers (Huazhu Fu, Haoyu Chen from Singapore/China institutions)
- **Ophtha-LLaMA2** (see §1.6) — Authors from Chinese universities
- **Wenzhou Medical University / Cixi Biomedical Research Institute** — Active in ophthalmology AI research but specific open-source VLM releases not confirmed as of early 2025

---

## 2. GraphRAG Implementations for Medical Knowledge Bases

### 2.1 Microsoft GraphRAG

| Field | Details |
|-------|---------|
| **Repository** | [microsoft/graphrag](https://github.com/microsoft/graphrag) |
| **Architecture** | Constructs knowledge graphs from documents using LLM-based entity/relationship extraction → community detection (Leiden algorithm) → hierarchical summarization → global/local search |
| **Medical Suitability** | ✅ High — excels at complex reasoning over interconnected medical knowledge; handles "what connects X to Y" queries well |
| **Strengths** | Global query capability (answers questions spanning entire corpus); structured knowledge representation; community-based summarization |
| **Weaknesses** | Expensive indexing (many LLM calls); slower query time; requires careful entity schema design for medical domains |
| **GPU Requirements** | Indexing requires significant LLM API calls or local GPU for embedding/extraction models |
| **Best For** | Comprehensive ophthalmology knowledge bases covering disease relationships, treatment protocols, drug interactions |

### 2.2 LightRAG

| Field | Details |
|-------|---------|
| **Repository** | [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG) |
| **Architecture** | Lightweight graph-based RAG with dual-level retrieval (low-level entities + high-level concepts); incremental graph updates without full re-indexing |
| **Medical Suitability** | ✅ High — specifically demonstrated for medical QA ([IEEE: LightRAG-Driven Medical QA](https://ieeexplore.ieee.org/document/11386653)) |
| **Strengths** | Much faster indexing than Microsoft GraphRAG; incremental updates; lower cost; good balance of local/global retrieval |
| **Weaknesses** | Less mature ecosystem; fewer production deployments documented |
| **Best For** | Rapidly evolving medical knowledge bases where new guidelines/papers are added frequently |

### 2.3 nano-graphrag

| Field | Details |
|-------|---------|
| **Repository** | [gusye1234/nano-graphrag](https://github.com/gusye1234/nano-graphrag) |
| **Architecture** | Minimalist reimplementation of GraphRAG concepts; pluggable LLM/embedding/storage backends |
| **Medical Suitability** | ⚠️ Moderate — flexible but requires more custom configuration for medical domains |
| **Strengths** | Extremely lightweight; easy to customize; minimal dependencies; good for prototyping |
| **Weaknesses** | Fewer built-in optimizations; less tested at scale |
| **Best For** | Prototyping medical GraphRAG systems; custom medical knowledge graph experiments |

### 2.4 Comparison Matrix

| Feature | Microsoft GraphRAG | LightRAG | nano-graphrag |
|---------|-------------------|----------|---------------|
| Indexing Speed | Slow (hours) | Fast (minutes) | Medium |
| Query Quality (Global) | ★★★★★ | ★★★★☆ | ★★★☆☆ |
| Query Quality (Local) | ★★★★☆ | ★★★★★ | ★★★★☆ |
| Incremental Updates | ❌ Full re-index | ✅ Native | ⚠️ Manual |
| Medical Domain Testing | Moderate | ✅ Published paper | Limited |
| Production Readiness | High | Medium | Low |
| Customizability | Medium | Medium | High |
| Cost (Indexing) | High ($$) | Low ($) | Low ($) |

**Recommendation for Ophthalmology:** Start with **LightRAG** for medical QA (proven in medical domain), use **Microsoft GraphRAG** for comprehensive knowledge base construction, and **nano-graphrag** for rapid prototyping.

---

## 3. Multi-Agent Frameworks for Medical AI

### 3.1 AutoGen (Microsoft)

| Field | Details |
|-------|---------|
| **Repository** | [microsoft/autogen](https://github.com/microsoft/autogen) |
| **Architecture** | Conversable agents with customizable roles; supports human-in-the-loop; nested conversations; code execution |
| **Medical Applications** | Multi-specialty consultation simulation; diagnostic reasoning chains; clinician-AI collaborative workflows |
| **Strengths** | Mature framework; extensive documentation; supports complex conversation patterns; code execution for analysis |
| **Weaknesses** | Can be verbose for simple workflows; steep learning curve for advanced patterns |
| **Best For** | Complex diagnostic workflows requiring multiple specialist perspectives |

### 3.2 CrewAI

| Field | Details |
|-------|---------|
| **Repository** | [crewAIInc/crewAI](https://github.com/crewAIInc/crewAI) |
| **Architecture** | Role-based agent teams with defined tasks, processes (sequential/hierarchical), and tools |
| **Medical Applications** | Structured diagnostic pipelines (e.g., Image Analyst → Differential Diagnoser → Treatment Recommender) |
| **Strengths** | Intuitive role/task abstraction; easy to define medical team structures; good for sequential diagnostic workflows |
| **Weaknesses** | Less flexible for dynamic/ad-hoc collaboration; newer framework |
| **Best For** | Well-defined ophthalmic diagnostic pipelines with clear role separation |

### 3.3 LangGraph

| Field | Details |
|-------|---------|
| **Repository** | [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) |
| **Architecture** | Stateful graph-based agent orchestration; nodes = agents/tools, edges = conditional routing; persistent state |
| **Medical Applications** | Complex diagnostic decision trees; adaptive workflows based on intermediate findings; audit trails |
| **Strengths** | Fine-grained control flow; conditional branching based on diagnostic confidence; state persistence for longitudinal patient analysis |
| **Weaknesses** | More complex to set up; requires understanding of graph-based programming |
| **Best For** | Adaptive diagnostic workflows where the path depends on intermediate VLM findings |

### 3.4 Specialized Medical Multi-Agent Systems

- **Multi-agent conversation for disease diagnosis** ([GitHub: geteff1/Multi-agent-conversation-for-disease-diagnosis](https://github.com/geteff1/Multi-agent-conversation-for-disease-diagnosis)) — Framework specifically designed for multi-agent LLM conversations for complex disease diagnosis
- **Medi-Agent** — Clinically aligned multimodal AI agent for CAD-assisted diagnosis and risk stratification
- **Asklepios** ([GitHub: zhuangwenhui/Asklepios](https://github.com/zhuangwenhui/Asklepios)) — Medical GraphRAG + agent system

---

## 4. Integration Architecture: VLM + GraphRAG + Multi-Agent for Ophthalmic Diagnosis

### 4.1 Recommended Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    PATIENT INTERFACE                         │
│              (Upload fundus image + symptoms)                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              ORCHESTRATOR AGENT (LangGraph)                   │
│         Routes workflow based on input type & complexity      │
└──────┬──────────────┬──────────────┬────────────────────────┘
       │              │              │
       ▼              ▼              ▼
┌────────────┐ ┌────────────┐ ┌────────────────┐
│ VLM AGENT  │ │ GRAPH-RAG  │ │ REPORT AGENT   │
│            │ │   AGENT    │ │                │
│ RetiZero / │ │ LightRAG / │ │ Generates      │
│ VisionUnite│ │ MS GraphRAG│ │ structured     │
│ / RETFound │ │ + Ophtho   │ │ clinical report│
│ + LLM      │ │ Knowledge  │ │ + explanations │
│            │ │ Graph      │ │                │
└──────┬─────┘ └──────┬─────┘ └───────┬────────┘
       │              │               │
       └──────────────┼───────────────┘
                      │
                      ▼
            ┌──────────────────┐
            │ REVIEW AGENT     │
            │ (Human-in-loop / │
            │ Confidence check)│
            └──────────────────┘
```

### 4.2 Component Roles

| Agent | Role | Technology | Input | Output |
|-------|------|-----------|-------|--------|
| **Orchestrator** | Routes cases, manages workflow state | LangGraph | Patient data + image | Workflow decisions |
| **VLM Agent** | Analyzes fundus image, generates preliminary findings | RetiZero/VisionUnite + Ophtha-LLaMA2 | Fundus photo | Disease probabilities, lesion descriptions |
| **GraphRAG Agent** | Retrieves relevant medical knowledge, guidelines, similar cases | LightRAG + ophthalmology KG | VLM findings + patient history | Evidence-based context, differential diagnoses |
| **Report Agent** | Synthesizes VLM + GraphRAG outputs into clinical report | LLM (Ophtha-LLaMA2 or general) | All prior outputs | Structured diagnostic report |
| **Review Agent** | Validates consistency, flags low-confidence findings | Rule-based + LLM | Complete report | Approval / escalation |

### 4.3 Data Flow Example: Diabetic Retinopathy Case

1. **Patient uploads** fundus photo + reports diabetes history
2. **Orchestrator** identifies this as a DR grading case → activates VLM + GraphRAG agents
3. **VLM Agent (RetiZero)** analyzes image → returns: "Severe NPDR, microaneurysms, hard exudates, cotton wool spots, confidence 0.89"
4. **GraphRAG Agent** queries knowledge base → retrieves: ETDRS grading criteria, latest ADA guidelines, similar case outcomes, referral thresholds
5. **Report Agent** synthesizes → generates structured report with DR grade, lesion inventory, guideline-referenced recommendations, follow-up schedule
6. **Review Agent** validates → confirms consistency between VLM findings and GraphRAG evidence; flags if discrepancy detected

### 4.4 Implementation Recommendations

| Decision | Recommendation | Rationale |
|----------|---------------|-----------|
| Primary VLM | **RetiZero** | Most comprehensive (400+ diseases), open-source, proven clinical utility |
| Secondary VLM | **VisionUnite** | Best conversational capability; use for patient interaction layer |
| Feature Extractor | **RETFound** | Use as backbone if building custom VLM; best pre-trained retinal features |
| GraphRAG Engine | **LightRAG** (primary) + **MS GraphRAG** (comprehensive KB) | LightRAG for fast queries; MS GraphRAG for deep knowledge base |
| Multi-Agent Framework | **LangGraph** | Best for adaptive diagnostic workflows with conditional branching |
| Ophthalmology LLM | **Ophtha-LLaMA2** | Best specialized ophthalmic text understanding |
| Knowledge Base Sources | AAO guidelines, ETDRS, ICROP, ophthalmology textbooks, PubMed abstracts | Build comprehensive ophthalmology KG for GraphRAG |

### 4.5 Practical Testing Roadmap

| Phase | Duration | Activities |
|-------|----------|------------|
| **Phase 1: VLM Evaluation** | 2-3 weeks | Test RetiZero, VisionUnite, RETFound on MESSIDOR-2/APTOS/REFUGE benchmarks; compare zero-shot vs fine-tuned performance |
| **Phase 2: GraphRAG Setup** | 2-3 weeks | Build ophthalmology knowledge graph from guidelines + literature; test LightRAG vs MS GraphRAG on ophthalmic QA |
| **Phase 3: Multi-Agent Integration** | 3-4 weeks | Implement LangGraph orchestrator; connect VLM + GraphRAG agents; test end-to-end diagnostic workflow |
| **Phase 4: Clinical Validation** | 4-6 weeks | Compare system outputs against ophthalmologist readings; iterate on prompts, knowledge graph, and workflow |

---

## 5. Summary Table: All Models at a Glance

| Model | Type | Open Source | Fundus Tasks | Best For | GPU Needed |
|-------|------|-------------|--------------|----------|------------|
| RetiZero | VLM (contrastive) | ✅ GitHub | 400+ diseases, zero-shot, retrieval | Multi-disease diagnosis, rare diseases | Yes |
| VisionUnite | VLM (generative) | ✅ GitHub | Multi-disease, dialogue, education | Patient interaction, clinical explanation | Yes |
| RETFound | Vision-only FM | ✅ HF/GitHub | DR, glaucoma, AMD, systemic (fine-tune) | Feature extraction, custom classifiers | Yes |
| MedDr | VLM (generalist) | ✅ HF/GitHub | Retinography + multi-specialty | Cross-specialty medical imaging | Yes |
| FLAIR | VLM (CLIP-style) | ⚠️ Limited | DR, glaucoma, AMD (zero-shot) | Expert-knowledge-aligned retrieval | Yes |
| Ophtha-LLaMA2 | Text LLM | ⚠️ Unclear | Report interpretation, diagnosis | Ophthalmic text understanding | Yes |
| EyeGPT | LLM assistant | ❌ Unconfirmed | Clinical assistance | TBD | Unknown |
| LLaVA-Med | VLM (generalist) | ✅ GitHub | Limited fundus (needs fine-tuning) | Baseline comparison | Yes |
| Med-PaLM-M | VLM (API only) | ❌ API | Some retinal capability | Upper-bound benchmark | N/A (API) |
| BiomedCLIP | VLM (CLIP) | ✅ HF | DR with fine-tuning | Lightweight DR screening | Yes |

---

## Sources

- [RetiZero - arXiv:2406.09317](https://arxiv.org/abs/2406.09317) | [GitHub](https://github.com/LooKing9218/RetiZero)
- [VisionUnite - arXiv:2408.02865](https://arxiv.org/abs/2408.02865) | [GitHub](https://github.com/HUANGLIZI/VisionUnite)
- [RETFound - Nature 2023](https://www.nature.com/articles/s41586-023-06555-x) | [GitHub](https://github.com/rmaphoh/RETFound_MAE) | [HuggingFace](https://huggingface.co/YukunZhou)
- [MedDr - arXiv:2404.15127](https://arxiv.org/abs/2404.15127) | [HuggingFace](https://huggingface.co/Sunanhe/MedDr_0401) | [GitHub](https://github.com/sunanhe/meddr)
- [FLAIR - Medical Image Analysis 2025](https://www.sciencedirect.com/science/article/abs/pii/S1361841524002822)
- [Ophtha-LLaMA2 - arXiv:2312.04906](https://arxiv.org/abs/2312.04906)
- [EyeGPT - Semantic Scholar](https://www.semanticscholar.org/paper/EyeGPT%3A-Ophthalmic-Assistant-with-Large-Language-Chen-Zhao/547ce91f3b7390c8887f91df8a7f97217fff7bf2)
- [BiomedCLIP DR Fine-Tuning - Stanford CS231N 2025](https://cs231n.stanford.edu/2025/papers/text_file_840579440-CS231N_Final_Report_2025%20(1).pdf)
- [LightRAG Medical QA - IEEE](https://ieeexplore.ieee.org/document/11386653)
- [Microsoft GraphRAG - GitHub](https://github.com/microsoft/graphrag)
- [LightRAG - GitHub](https://github.com/HKUDS/LightRAG)
- [nano-graphrag - GitHub](https://github.com/gusye1234/nano-graphrag)
- [AutoGen - GitHub](https://github.com/microsoft/autogen)
- [CrewAI - GitHub](https://github.com/crewAIInc/crewAI)
- [LangGraph - GitHub](https://github.com/langchain-ai/langgraph)
- [Multi-agent Disease Diagnosis - GitHub](https://github.com/geteff1/Multi-agent-conversation-for-disease-diagnosis)
- [Asklepios Medical GraphRAG - GitHub](https://github.com/zhuangwenhui/Asklepios)
- [Med-PaLM-M - NEJM AI](https://ai.nejm.org/doi/10.1056/AIoa2300138)
