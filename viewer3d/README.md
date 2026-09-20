# GE360 viewer3d

Minimal Three.js viewer for the independent GE360 `plan3d.json` format. It is intentionally not the openPlan3D application and does not own GE360 data.

Run the backend and open:

`http://127.0.0.1:8796/viewer3d/?plan=/api/v1/plans/PLAN_ID/3d`

Controls: OrbitControls mouse/touch orbit, pan and zoom plus Top, Perspective and Reset buttons. Walls are split around door/window openings; floors come from room polygons.
