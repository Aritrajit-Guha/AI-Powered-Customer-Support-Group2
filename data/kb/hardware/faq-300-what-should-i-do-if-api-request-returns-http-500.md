---
title: What should I do if API request returns HTTP 500?
category: Hardware
keywords: hardware, what, should, request, returns, http
---
Question: What should I do if API request returns HTTP 500?

Suggested answer: Capture the full command, working directory and error output. Confirm runtime/tool version, environment variables, permissions, network access and dependency versions. Activate the intended virtual environment and use the project's documented package manager. For Git conflicts, preserve local changes and resolve files deliberately. For HTTP errors, inspect authentication, authorization, endpoint, payload and server logs. Never share secrets or tokens. IT Hardware & Software Troubleshooting FAQ Page 32 APPENDIX — PREPARING THIS FAQ FOR RAG Suggested record structure Field Purpose Example id Unique identifier HW-001 / SW-001 category Issue group VPN, authentication and remote access question User-style query What should I do if VPN cannot connect? answer Troubleshooting steps Verify internet access and approved VPN settings... source Content provenance Internal IT FAQ / vendor guide last_reviewed Review date YYYY-MM-DD audience Intended reader End user / service desk Recommended RAG workflow 1. Store every FAQ as one independent question-and-answer record; never separate the question from its answer. 2. Keep category, issue type, source and review date as metadata to support filtering and traceability. 3. Normalize wording, remove duplicates and add common synonyms or alternate user phrasings. 4. Generate embeddings from the question and answer, or use separate question and answer fields according to the retrieval design. 5. Retrieve relevant records before generation. Instruct the model to answer from retrieved material and say when the knowledge base is insufficient. 6. Evaluate with unseen test questions. Check retrieval relevance, factual correctness, safe escalation and whether the answer invents unsupported procedures. Limitations and maintenance This is a general starter knowledge base. It does not include organization-specific VPN gateways, network names, software versions, warranty details, service-level agreements or internal escalation contacts. Troubleshooting varies by operating system, device manufacturer and enterprise configuration. Have a qualified IT administrator review and adapt the content before deployment. Track sources and review dates, and retire outdated procedures. End of document — 150 hardware FAQs + 150 software FAQs = 300 total Q&A entries.

Steps:
1. Follow the safe first-line checks described in the suggested answer.
2. Record any exact error, status light, diagnostic code, or observed symptom.
3. Stop and request authorized support if the issue persists or the check is unsafe.

Escalate if: the issue continues, affects multiple users, or involves physical danger, suspected compromise, or possible data loss.

Safety note: These are general first-line checks. Do not open equipment, alter firmware, change corporate network or security settings, bypass MFA, disable endpoint protection, or modify production data without authorization.
