import sys
errors = []

def chk(label, fn):
    try:
        fn()
        print("  OK  " + label)
    except Exception as e:
        print("  FAIL " + label + ": " + str(e))
        errors.append(label)

chk("pytesseract",  lambda: __import__("pytesseract"))
chk("Pillow",       lambda: __import__("PIL"))
chk("opencv",       lambda: __import__("cv2"))
chk("python-docx",  lambda: __import__("docx"))
chk("openpyxl",     lambda: __import__("openpyxl"))
chk("python-pptx",  lambda: __import__("pptx"))

print("")
if errors:
    print(str(len(errors)) + " fout(en): " + ", ".join(errors))
    sys.exit(1)
else:
    print("Alle checks OK")
    sys.exit(0)
