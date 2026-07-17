from hashlib import sha1

from lead_cleaner.rag.schemas import KnowledgeChunk, KnowledgeDocument


def _get_page_title_line(document: KnowledgeDocument) -> str:
    for line in document.text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped

    return f"# {document.source_title}"


def _build_chunk_id(
    source_path: str,
    section: str,
    chunk_index: int,
) -> str:
    raw_value = f"{source_path}|{section}|{chunk_index}"
    digest = sha1(raw_value.encode("utf-8")).hexdigest()[:12]
    return f"chunk_{digest}"


def split_text_by_heading_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []

    current_section: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("## "):
            if current_section is not None and current_lines:
                section_text = "\n".join(current_lines).strip()
                if section_text:
                    sections.append((current_section, section_text))

            current_section = stripped.removeprefix("## ").strip()
            current_lines = [stripped]
            continue

        if current_section is not None:
            current_lines.append(line.rstrip())

    if current_section is not None and current_lines:
        section_text = "\n".join(current_lines).strip()
        if section_text:
            sections.append((current_section, section_text))

    return sections


def chunk_document_by_heading_sections(
    document: KnowledgeDocument,
) -> list[KnowledgeChunk]:
    page_title_line = _get_page_title_line(document)
    sections = split_text_by_heading_sections(document.text)

    if not sections:
        sections = [(document.source_title, document.text.strip())]

    chunks: list[KnowledgeChunk] = []

    for chunk_index, (section, section_text) in enumerate(sections):
        if section_text.startswith("# "):
            chunk_text = section_text
        else:
            chunk_text = f"{page_title_line}\n{section_text}".strip()

        chunk = KnowledgeChunk(
            chunk_id=_build_chunk_id(
                source_path=document.source_path,
                section=section,
                chunk_index=chunk_index,
            ),
            source_type=document.source_type,
            notion_page_id=document.notion_page_id,
            source_title=document.source_title,
            source_path=document.source_path,
            doc_type=document.doc_type,
            region=document.region,
            product_name=document.product_name,
            section=section,
            chunk_index=chunk_index,
            chunk_strategy="heading_section",
            text=chunk_text,
            last_edited_time=document.last_edited_time,
        )
        chunks.append(chunk)

    return chunks


def chunk_documents_by_heading_sections(
    documents: list[KnowledgeDocument],
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []

    for document in documents:
        chunks.extend(chunk_document_by_heading_sections(document))

    return chunks

