from docx2python import docx2python

# Extract docx content
with docx2python('./docs/РСУ_адаптированная.docx') as docx_content:
    print(docx_content.text)