from __future__ import annotations
from dataclasses import dataclass
from typing import Any,Literal
from pydantic import BaseModel,ValidationError
from .schemas import *

ToolKind=Literal["read","mutation","control"]
@dataclass(frozen=True)
class ToolSpec: name:CADToolName; description:str; args_model:type[BaseModel]; kind:ToolKind

_SPECS=(
ToolSpec(CADToolName.GET_PLAN,"Inspect current plan metadata.",EmptyArgs,"read"),
ToolSpec(CADToolName.GET_PLAN_SUMMARY,"Get compact semantic plan summary.",EmptyArgs,"read"),
ToolSpec(CADToolName.GET_WALL,"Inspect wall by id.",GetWallArgs,"read"),
ToolSpec(CADToolName.GET_WALLS,"Filter existing walls semantically.",GetWallsArgs,"read"),
ToolSpec(CADToolName.GET_ROOM,"Inspect room.",GetRoomArgs,"read"),
ToolSpec(CADToolName.GET_ROOMS,"List rooms.",EmptyArgs,"read"),
ToolSpec(CADToolName.FIND_NEAREST_WALL,"Rank wall candidates from semantic description.",FindNearestWallArgs,"read"),
ToolSpec(CADToolName.CREATE_WALL,"Create candidate wall from topology refs and measurements.",CreateWallArgs,"mutation"),
ToolSpec(CADToolName.MODIFY_WALL,"Modify candidate wall.",ModifyWallArgs,"mutation"),
ToolSpec(CADToolName.DELETE_WALL,"Delete candidate wall.",DeleteWallArgs,"mutation"),
ToolSpec(CADToolName.MOVE_WALL,"Move candidate wall by delta.",MoveWallArgs,"mutation"),
ToolSpec(CADToolName.MOVE_VERTEX,"Move topology vertex by delta.",MoveVertexArgs,"mutation"),
ToolSpec(CADToolName.SPLIT_WALL,"Split wall.",SplitWallArgs,"mutation"),
ToolSpec(CADToolName.CONNECT_WALLS,"Connect nearest endpoints of two walls.",ConnectWallsArgs,"mutation"),
ToolSpec(CADToolName.CREATE_DOOR,"Create hosted door.",CreateOpeningArgs,"mutation"),
ToolSpec(CADToolName.CREATE_WINDOW,"Create hosted window.",CreateOpeningArgs,"mutation"),
ToolSpec(CADToolName.MODIFY_OPENING,"Modify door/window.",ModifyOpeningArgs,"mutation"),
ToolSpec(CADToolName.DELETE_OPENING,"Delete opening.",DeleteOpeningArgs,"mutation"),
ToolSpec(CADToolName.ADD_ANNOTATION,"Add construction annotation.",AddAnnotationArgs,"mutation"),
ToolSpec(CADToolName.ADD_CONSTRAINT,"Add explicit GE360 constraint.",AddConstraintArgs,"mutation"),
ToolSpec(CADToolName.REMOVE_CONSTRAINT,"Remove explicit constraint.",RemoveConstraintArgs,"mutation"),
ToolSpec(CADToolName.SOLVE_PLAN,"Run deterministic solver.",EmptyArgs,"mutation"),
ToolSpec(CADToolName.VALIDATE_PLAN,"Run deterministic validator.",EmptyArgs,"mutation"),
ToolSpec(CADToolName.GENERATE_PREVIEW,"Generate candidate preview.",EmptyArgs,"mutation"),
ToolSpec(CADToolName.APPLY_CHANGES,"Apply candidate after explicit confirmation.",ApplyChangesArgs,"control"),
ToolSpec(CADToolName.UNDO,"Restore prior version.",UndoRedoArgs,"control"),
ToolSpec(CADToolName.REDO,"Restore later version.",UndoRedoArgs,"control"),
)
class ToolRegistry:
    def __init__(self): self._specs={x.name.value:x for x in _SPECS}
    @property
    def names(self): return tuple(x.name.value for x in _SPECS)
    def get(self,name:str)->ToolSpec:
        if name not in self._specs: raise ValueError(f"Tool not allowed: {name}")
        return self._specs[name]
    def validate_arguments(self,name:str,args:dict[str,Any])->BaseModel:
        try: return self.get(name).args_model.model_validate(args)
        except ValidationError as exc: raise ValueError(f"Invalid arguments for {name}: {exc}") from exc
    def openai_tools(self,*,include_control:bool=False):
        out=[]
        for s in _SPECS:
            if s.kind=="control" and not include_control: continue
            out.append({"type":"function","function":{"name":s.name.value,"description":s.description,"parameters":s.args_model.model_json_schema()}})
        return out
REGISTRY=ToolRegistry()
