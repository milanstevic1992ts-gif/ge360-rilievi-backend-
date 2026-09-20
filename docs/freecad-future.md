# FreeCAD future integration

FreeCAD is deliberately outside the V1 critical path. `freecad-mcp` and AgentCAD were reviewed for architecture, not imported.

A later worker may translate a validated `GE360Plan` into structured commands such as create document, create wall/slab/opening entities, validate the document and export IFC/STEP/FCStd. That worker must run out-of-process, must receive only the validated GE360 model, and must never become the source of truth for `declaredLengthMm`, opening width/offset or other authoritative survey data.

The preferred design is `GE360Plan -> FreeCAD adapter/worker -> artifact`, with explicit timeouts and failure isolation. A missing FreeCAD installation must never prevent JSON/DXF/SVG/PNG/PDF/plan3d output.
