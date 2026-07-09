# 🛡️ NiyamGuard AI

> **An Autonomous Trust & Synchronization Layer for Digital Public Infrastructure (DPI)**

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.12-blue.svg)
![React](https://img.shields.io/badge/react-18.x-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)

NiyamGuard AI is an end-to-end Government-to-Citizen (G2C) policy compliance and citizen assistance ecosystem designed specifically for the Indian administrative context. It bridges the critical gap between complex, constantly evolving government circulars and the everyday citizens who need to access state services (e.g., MeeSeva certificates, Income, and EWS verification).

---

## 📖 Table of Contents
- [The Problem](#-the-problem)
- [The Solution](#-the-solution)
- [Architecture & Modules](#-architecture--modules)
- [Key Features](#-key-features)
- [Tech Stack](#-tech-stack)
- [Safety & Ethical Guardrails](#-safety--ethical-guardrails)
- [Local Development Setup](#-local-development-setup)
- [Testing](#-testing)
- [Author](#-author)

---

## 🚨 The Problem
Government policies and service constraints (like income limits for EWS or validity periods for certificates) change rapidly via unformatted PDF circulars. 
1. **The Gov Problem:** Downstream systems (portals, officer SOPs, public FAQs) often suffer from "policy drift," displaying outdated information.
2. **The Citizen Problem:** First-time users, elderly citizens, and rural populations find official forms deeply intimidating, linguistically rigid, and difficult to navigate without predatory third-party assistance.

---

## 💡 The Solution
NiyamGuard acts as a two-sided synchronization layer:
* **For the Government:** It ingests raw PDF circulars, uses LLMs to extract structural rules, cryptographically logs them, and scans all connected government systems for compliance drift.
* **For the Citizen:** It provides a beautifully minimal, natively multilingual voice assistant that guides users through dynamic forms based *strictly* on the verified, updated rules. 

---

## 🏗 Architecture & Modules

The platform operates across two primary domains:

### 1. Government Policy & Audit Engine (Backend)
A hardened, secure backend for government officials to ingest and track policy changes.
* **LLM Extraction Pipeline:** Extracts rule deltas from raw text or PDFs using Gemini/Anthropic with strict exponential backoff and rate-limiting.
* **Hash-Chained Audit Ledger:** Ensures that once a rule is verified by a reviewer, its lifecycle is tamper-evident.
* **RBAC:** Strict Role-Based Access Control (`viewer`, `reviewer`, `admin`) backed by per-user JWTs.

### 2. Citizen Assistant & Gov Core (Frontend & API)
The interactive portal for citizens and the logic for system compliance.
* **Voice/Form Assistant:** Provides text and voice guidance in Telugu, Hindi, and English. 
* **Dynamic Form Rendering:** UI dynamically generates based on JSON schemas (incorporating a minimal, *folk.*-inspired design system).
* **Cascade Tracing:** Identifies which interconnected systems (e.g., MeeSeva portals) are out-of-sync with the latest verified rules.

---

## ✨ Key Features
* **Multilingual Fallback Matrix:** Attempts local Whisper STT transcription, gracefully falling back to browser-native `SpeechRecognition`. Uses `gTTS` backend caching when native regional browser voices are missing.
* **Smart Contextual Memory:** The voice assistant knows which specific form field the citizen is currently focused on and provides hyper-local advice (e.g., Telangana Mandal/Pincode lookup).
* **Cross-Circular Conflict Detection:** Automatically warns reviewers if a newly extracted circular contradicts an active older circular.

---

## 💻 Tech Stack

**Frontend:**
* React + Vite
* Custom CSS (Variables, Flexbox, Minimal CRM aesthetic)
* Web Speech API (SpeechRecognition & SpeechSynthesis)

**Backend & Data:**
* Python 3.12 + FastAPI
* PostgreSQL 16 (Relational Schema)
* SQLAlchemy + Alembic (Migrations)
* Docker & Docker Compose

**AI & Processing:**
* Gemini 2.5 Flash / Claude 3.5 Sonnet (Policy Extraction)
* Faster-Whisper (Local STT)
* gTTS (Text-to-Speech)

---

## 🛡 Safety & Ethical Guardrails
NiyamGuard is built with strict limits to protect both the citizen and the state:
1. **Zero Auto-Fill:** The assistant provides suggested values and guidance, but **never** types into fields automatically. 
2. **Citizen Control:** The assistant **never** autonomously uploads files or clicks submit.
3. **Demo Boundary:** The current MVP simulates the final submission. It explicitly warns users that it does not call real government APIs yet.
4. **Human-in-the-Loop:** Extracted policies are never pushed to the live database without manual approval logged by a reviewer.

---

## 🚀 Local Development Setup

### Prerequisites
* Docker & Docker Compose
* Node.js 18+
* Python 3.12

### 1. Start the Government Core Backend (Docker)
```bash
cd backend
cp .env.example .env
# Edit .env with your Gemini API key and secrets
docker-compose up -d --build
