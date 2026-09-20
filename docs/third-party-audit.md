# GE360 third-party audit

Audit date: 2026-09-20. The source checkouts were inspected through GitHub because the development container could not resolve `github.com` for `git clone`. No complete external repository is committed into GE360.

| Project | Analyzed commit | License | Useful parts | GE360 decision |
| --- | --- | --- | --- | --- |
| [archit-app](https://github.com/archit-app/archit-app) | `e2913370845bfe2523c57862a2ef19badbd84056` | MIT | `Wall.straight`, `Opening`, `Polygon2D`, validation concepts, `archit_app.io.dxf` | **OPTIONAL DEPENDENCY + ADAPTER.** No source copied. `backend/integrations/archit_adapter.py` converts mm→m and verifies wall lengths on round trip. It is not authoritative and is not required by the MVP. |
| [ArchLang](https://github.com/ChanMeng666/archlang) | `9b2aa2d47d7f5e627471578e23e203fb7066d39c` | MIT | parser/IR, Plan JSON, diagnostics, agent-oriented declarative language | **NOT USED AT RUNTIME V1.** Pure TypeScript; JSON tool calling is smaller and keeps the Python backend independent. `archlang_adapter.py` is only a future boundary. |
| [openPlan3D](https://github.com/laanlabs/openPlan3D) | `d68cadf703578f2cd3a7c77f820e18d342580c32` | MIT | `wallProfiles.ts`, `slopedWallGeometry.ts`, `frameScene.ts`, `orbitDamping.ts`, `ThreeViewer.svelte`, room/viewer patterns | **CONCEPTS + ADAPTER.** Do not copy the Svelte application. GE360 emits independent `plan3d.json`; `openplan3d_adapter.py` can map to a viewer-oriented model. The standalone viewer uses Three.js directly. |
| [freecad-mcp](https://github.com/blwfish/freecad-mcp) | `48c9376d67328d09bbed48656f6f12a752058676` | LGPL-2.1-or-later | structured tool schemas, document/entity creation, export/headless patterns | **REFERENCE ONLY V1.** FreeCAD is not a required dependency. See `docs/freecad-future.md`. |
| [AgentCAD](https://github.com/Getopir/AgentCAD) | `71446647d4f5ed7186eea8d412599b7b84141a8c` | LGPL-2.1-or-later | typed worker protocol, transaction/validation architecture, structured CAD execution | **REFERENCE ONLY V1.** No code copied; project is pre-alpha and FreeCAD-oriented. |

## ezdxf

`ezdxf` is consumed as a normal Python dependency, never vendored. GE360 creates a structured R2018 DXF with millimetre units and the layers `GE360_WALLS`, `GE360_DOORS`, `GE360_WINDOWS`, `GE360_ROOMS`, `GE360_DIMENSIONS`, `GE360_TEXT`. Every produced DXF is reopened and audited with `ezdxf` before the pipeline publishes the current version.

## Vendor directory

`backend/third_party/` intentionally contains no copied external source at this stage. If a future module must be vendored, its directory must include the upstream LICENSE and a SOURCE.md recording URL, commit, copied files, reason and modifications.
