# Dependency decisions

## archit-app

Repository: https://github.com/archit-app/archit-app
License checked: MIT.

It provides a Python architectural model, non-Manhattan geometry and export facilities. GE360 does not make it a runtime dependency in v1 because GE360 must preserve its own measurement-authority rules and raw frontend contract, and adding a second architectural model would increase translation/validation surface.

Decision: study and optionally add an adapter later. Keep GE360 PlanModel independent.

## openPlan3D

Repository: https://github.com/laanlabs/openPlan3D
License checked: MIT.

Useful concepts include Three.js navigation, wall/opening rendering and 3D interaction. GE360 does not adopt its project model as the backend source of truth.

Decision: reuse concepts through an adapter/viewer layer only. plan3d.json and GLB are generated from the GE360 PlanModel.

## FreeCAD / OpenCascade

Not required for v1. Candidates for advanced CAD/BIM operations later.
