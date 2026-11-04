# Support knowledge base

These Markdown articles are the source records for the Person B RAG pipeline.
The current set contains one record for each of the 300 questions in the
attached IT Hardware & Software Troubleshooting FAQ, assigned to the project's
seven categories. The original question and suggested answer are preserved,
with structured steps and safety guidance added for retrieval and resolution
generation. Additional generated articles cover sparse Security, Email, and
Password Reset topics.

Run the indexer from the repository root:

```text
python -m rag.index_kb
```

To regenerate the records from the PDF:

```text
python -m rag.import_pdf
```
