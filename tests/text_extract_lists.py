from docx import Document

doc = Document("test.docx")

lists = []
current_list = []
collecting = False

for p in doc.paragraphs:
    text = p.text.strip()

    # 1. Вводная строка со двоеточием
    if text.endswith(":") and text:
        if current_list:
            lists.append(current_list)
            current_list = []
        collecting = True
        continue

    # 2. Пустая строка — конец списка
    if not text:
        if collecting and current_list:
            lists.append(current_list)
            current_list = []
        collecting = False
        continue

    # 3. Элемент ненумерованного списка
    if collecting:
        current_list.append(text)

# на случай если список в конце документа
if current_list:
    lists.append(current_list)

for i, lst in enumerate(lists, 1):
    print(f"Список {i}:")
    for item in lst:
        print(" -", item)
