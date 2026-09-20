from __future__ import annotations
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictModel(BaseModel):
    model_config=ConfigDict(extra="forbid")

class CADToolName(str,Enum):
    GET_PLAN="get_plan"; GET_PLAN_SUMMARY="get_plan_summary"; GET_WALL="get_wall"; GET_WALLS="get_walls"; GET_ROOM="get_room"; GET_ROOMS="get_rooms"; FIND_NEAREST_WALL="find_nearest_wall"
    CREATE_WALL="create_wall"; MODIFY_WALL="modify_wall"; DELETE_WALL="delete_wall"; MOVE_WALL="move_wall"; MOVE_VERTEX="move_vertex"; SPLIT_WALL="split_wall"; CONNECT_WALLS="connect_walls"
    CREATE_DOOR="create_door"; CREATE_WINDOW="create_window"; MODIFY_OPENING="modify_opening"; DELETE_OPENING="delete_opening"; ADD_ANNOTATION="add_annotation"
    ADD_CONSTRAINT="add_constraint"; REMOVE_CONSTRAINT="remove_constraint"; SOLVE_PLAN="solve_plan"; VALIDATE_PLAN="validate_plan"; GENERATE_PREVIEW="generate_preview"
    APPLY_CHANGES="apply_changes"; UNDO="undo"; REDO="redo"

class SelectedObject(StrictModel):
    type: Literal["wall","room","opening","node","constraint","point"]
    id:str|None=None; wall_id:str|None=None; offset_mm:float|None=None; label:str|None=None

class CADPlannerRequest(StrictModel):
    instruction:str=Field(min_length=1,max_length=4000)
    selected_object:SelectedObject|None=Field(default=None,alias="selectedObject")
    selected_objects:list[SelectedObject]=Field(default_factory=list,alias="selectedObjects",max_length=20)
    auto_preview:bool=Field(default=True,alias="autoPreview")
    best_effort:bool=Field(default=True,alias="bestEffort")
    mode:Literal["AUTO","CAD_PLANNER","SURVEY_ASSISTANT","CONSTRUCTION_ANNOTATOR","SOLVER_EXPLAINER","PLAN_REPAIR_PLANNER"]="AUTO"

class TargetCandidate(StrictModel):
    type:Literal["wall","room","opening","node","constraint"]; id:str; confidence:float=Field(ge=0,le=1); label:str|None=None; evidence:dict[str,Any]=Field(default_factory=dict)

class CADOperation(StrictModel):
    tool:CADToolName; arguments:dict[str,Any]=Field(default_factory=dict); confidence:float=Field(default=1.0,ge=0,le=1); reason:str|None=None

class CADCommandBatch(StrictModel):
    request_id:str; prompt_version:str; operations:list[CADOperation]=Field(min_length=1); requires_preview:bool=True; requires_solver:bool=True; destructive:bool=False

class PlannerResult(StrictModel):
    request_id:str; status:Literal["ready","ambiguous","unavailable","invalid","no_action"]; mode:str="CAD_PLANNER"; degraded:bool=False; best_effort_used:bool=False
    critic:dict[str,Any]=Field(default_factory=dict); command:CADCommandBatch|None=None; candidates:list[TargetCandidate]=Field(default_factory=list); message:str|None=None; tools_called:list[dict[str,Any]]=Field(default_factory=list)

class CandidatePreview(StrictModel):
    candidate_id:str; request_id:str; plan_id:str; base_version:int; status:Literal["ready","invalid"]; validation:dict[str,Any]; diff:dict[str,Any]; preview_url:str|None=None; command:CADCommandBatch

class EmptyArgs(StrictModel): pass
class GetWallArgs(StrictModel): wall_id:str
class GetWallsArgs(StrictModel):
    orientation:Literal["horizontal","vertical","diagonal"]|None=None; room:str|None=None; approx_length_m:float|None=Field(default=None,gt=0)
class GetRoomArgs(StrictModel):
    room_id:str|None=None; name:str|None=None
    @model_validator(mode="after")
    def selector(self):
        if not self.room_id and not self.name: raise ValueError("room_id or name is required")
        return self
class FindNearestWallArgs(StrictModel):
    orientation:Literal["horizontal","vertical","diagonal"]|None=None; approx_length_m:float|None=Field(default=None,gt=0); room:str|None=None
    side:Literal["left","right","top","bottom"]|None=None; near_opening_type:Literal["door","window"]|None=None

class CreateWallArgs(StrictModel):
    start_node_id:str; end_node_id:str|None=None; length_mm:float|None=Field(default=None,gt=0); direction:Literal["left","right","up","down"]|None=None
    thickness_mm:float|None=Field(default=None,gt=0); height_mm:float|None=Field(default=None,gt=0)
    @model_validator(mode="after")
    def endpoint_or_length(self):
        if not self.end_node_id and (self.length_mm is None or self.direction is None): raise ValueError("end_node_id or length_mm+direction required")
        return self
class ModifyWallArgs(StrictModel):
    wall_id:str; length_mm:float|None=Field(default=None,gt=0); thickness_mm:float|None=Field(default=None,gt=0); height_mm:float|None=Field(default=None,gt=0); angle_deg:float|None=None
    @model_validator(mode="after")
    def changed(self):
        if all(x is None for x in (self.length_mm,self.thickness_mm,self.height_mm,self.angle_deg)): raise ValueError("wall change required")
        return self
class DeleteWallArgs(StrictModel): wall_id:str
class MoveWallArgs(StrictModel): wall_id:str; delta_mm:float=Field(gt=0); direction:Literal["left","right","up","down"]
class MoveVertexArgs(StrictModel): node_id:str; delta_mm:float=Field(gt=0); direction:Literal["left","right","up","down"]
class SplitWallArgs(StrictModel): wall_id:str; distance_from_start_mm:float=Field(gt=0)
class ConnectWallsArgs(StrictModel):
    wall_a:str; wall_b:str
    @model_validator(mode="after")
    def distinct(self):
        if self.wall_a==self.wall_b: raise ValueError("wall_a and wall_b must differ")
        return self
class CreateOpeningArgs(StrictModel):
    wall_id:str; width_mm:float=Field(gt=0); offset_mm:float|None=Field(default=None,ge=0); reference_end:Literal["a","b"]="a"; height_mm:float|None=Field(default=None,gt=0); sill_height_mm:float|None=Field(default=None,ge=0)
class ModifyOpeningArgs(StrictModel):
    opening_id:str; width_mm:float|None=Field(default=None,gt=0); offset_mm:float|None=Field(default=None,ge=0); offset_delta_mm:float|None=None; height_mm:float|None=Field(default=None,gt=0); sill_height_mm:float|None=Field(default=None,ge=0)
    @model_validator(mode="after")
    def changed(self):
        if all(x is None for x in (self.width_mm,self.offset_mm,self.offset_delta_mm,self.height_mm,self.sill_height_mm)): raise ValueError("opening change required")
        return self
class DeleteOpeningArgs(StrictModel): opening_id:str
class AddAnnotationArgs(StrictModel):
    target_type:Literal["plan","room","wall","opening","ceiling","floor"]; target_id:str|None=None
    category:Literal["note","demolition","new_work","tiling","flooring","ceiling","plasterboard","painting","measurement"]="note"; text:str=Field(min_length=1,max_length=1000)
class AddConstraintArgs(StrictModel):
    kind:Literal["connect","parallel","perpendicular","collinear"]; wall_ids:list[str]=Field(default_factory=list,max_length=8); node_ids:list[str]=Field(default_factory=list,max_length=8)
    @model_validator(mode="after")
    def refs(self):
        if self.kind in {"parallel","perpendicular","collinear"} and len(self.wall_ids)!=2: raise ValueError("angular constraints require two walls")
        if self.kind=="connect" and len(self.wall_ids)<2 and len(self.node_ids)<2: raise ValueError("connect requires two refs")
        return self
class RemoveConstraintArgs(StrictModel): constraint_id:str
class ApplyChangesArgs(StrictModel): candidate_id:str
class UndoRedoArgs(StrictModel): steps:int=Field(default=1,ge=1,le=20)
