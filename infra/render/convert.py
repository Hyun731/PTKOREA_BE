"""Load a PPTX in headless LibreOffice, turn off Asian/Latin auto-spacing, export PDF.

LibreOffice applies 'spacing between Asian and non-Asian text' to imported paragraphs;
PowerPoint does not, so leaving it on makes the preview diverge from the real output.
Usage: python3 convert.py <in.pptx> <out.pdf>
"""
import subprocess
import sys
import time

import uno
from com.sun.star.beans import PropertyValue


def prop(name, value):
    p = PropertyValue()
    p.Name, p.Value = name, value
    return p


def fix_text(text_obj):
    try:
        enum = text_obj.createEnumeration()
    except Exception:
        return
    while enum.hasMoreElements():
        para = enum.nextElement()
        try:
            para.ParaIsCharacterDistance = False
        except Exception:
            pass


def walk(shapes):
    for i in range(shapes.Count):
        shape = shapes.getByIndex(i)
        kind = shape.ShapeType
        if kind == "com.sun.star.drawing.GroupShape":
            walk(shape)
        elif kind == "com.sun.star.drawing.TableShape":
            model = shape.Model
            for r in range(model.Rows.Count):
                for c in range(model.Columns.Count):
                    fix_text(model.getCellByPosition(c, r).getText())
        elif hasattr(shape, "getText"):
            try:
                fix_text(shape.getText())
            except Exception:
                pass


def main(inp, out):
    proc = subprocess.Popen(["soffice", "--headless", "--invisible", "--norestore", "--nologo",
                             "--accept=pipe,name=ptkrender;urp;"])
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
        ctx = None
        for _ in range(120):
            try:
                ctx = resolver.resolve("uno:pipe,name=ptkrender;urp;StarOffice.ComponentContext")
                break
            except Exception:
                time.sleep(0.5)
        if ctx is None:
            raise SystemExit("soffice did not start")
        desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        doc = desktop.loadComponentFromURL(uno.systemPathToFileUrl(inp), "_blank", 0, (prop("Hidden", True),))
        pages = doc.DrawPages
        for i in range(pages.Count):
            walk(pages.getByIndex(i))
        doc.storeToURL(uno.systemPathToFileUrl(out), (prop("FilterName", "impress_pdf_Export"),))
        doc.close(True)
    finally:
        proc.terminate()
        proc.wait(timeout=30)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
