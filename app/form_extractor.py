from __future__ import annotations

from app.models import FieldMetadata

FIELD_SELECTOR = "input:not([type=hidden]), textarea, select"


async def extract_form_fields(page) -> list[FieldMetadata]:
    handles = await page.locator(FIELD_SELECTOR).element_handles()
    fields: list[FieldMetadata] = []
    for index, handle in enumerate(handles):
        data = await handle.evaluate(
            """(el) => {
                const id = el.id || '';
                const label = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : null;
                const wrappingLabel = el.closest('label');
                const parent = el.parentElement;
                const options = el.tagName.toLowerCase() === 'select'
                    ? Array.from(el.options).map(o => o.textContent.trim()).filter(Boolean)
                    : [];
                return {
                    tag: el.tagName.toLowerCase(),
                    input_type: el.getAttribute('type'),
                    name: el.getAttribute('name'),
                    label: label?.textContent?.trim() || wrappingLabel?.textContent?.trim() || '',
                    placeholder: el.getAttribute('placeholder'),
                    aria_label: el.getAttribute('aria-label'),
                    nearby_text: parent?.innerText?.trim()?.slice(0, 300) || '',
                    options,
                    id,
                };
            }"""
        )
        selector = _selector_for(data, index)
        fields.append(FieldMetadata(selector=selector, **{k: v for k, v in data.items() if k != "id"}))
    return fields


def _selector_for(data: dict, index: int) -> str:
    if data.get("id"):
        return f"#{css_escape(data['id'])}"
    if data.get("name"):
        name = str(data["name"]).replace("'", "\\'")
        return f"[name='{name}']"
    return f"{FIELD_SELECTOR} >> nth={index}"


def css_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("#", "\\#").replace(".", "\\.").replace(":", "\\:").replace(" ", "\\ ")
