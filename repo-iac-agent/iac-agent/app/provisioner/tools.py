"""
Tools the provisioning LLMs can call. Each has a Pydantic args schema so the
model's arguments are validated before anything runs. All return strings
(JSON or plain text); failures come back as "ERROR: ..." so the model can
adjust rather than the pipeline crashing.
"""

import json
from typing import List, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from . import checks, registry
from .schemas import TerraformFile


class SearchProvidersArgs(BaseModel):
    query: str = Field(..., description="Cloud or vendor name as the user said it, e.g. 'oracle', 'hetzner', 'alibaba'")


class ListResourcesArgs(BaseModel):
    provider_source: str = Field(..., description="Registry address like 'hetznercloud/hcloud'")
    keyword: str = Field("", description="Substring to filter resource names, e.g. 'database', 'bucket', 'network'")
    category: Literal["resources", "data-sources"] = "resources"


class ResourceDocArgs(BaseModel):
    provider_source: str
    resource_type: str = Field(..., description="Full Terraform type, e.g. 'hcloud_server'")
    category: Literal["resources", "data-sources"] = "resources"


class FilesArgs(BaseModel):
    files: List[TerraformFile]


def _safe(fn):
    def run(**kwargs):
        try:
            return fn(**kwargs)
        except (registry.RegistryError, ValueError) as exc:
            return f"ERROR: {exc}"
        except Exception as exc:  # tool failures must never kill the stage
            return f"ERROR: {type(exc).__name__}: {exc}"

    return run


def _search_providers(query: str) -> str:
    return json.dumps(registry.search_providers(query))


def _list_resources(provider_source: str, keyword: str = "", category: str = "resources") -> str:
    names = registry.list_resources(provider_source, keyword, category)
    if not names:
        return f"No {category} matching {keyword!r} in {provider_source}. Try a broader keyword."
    return json.dumps(names)


def _resource_doc(provider_source: str, resource_type: str, category: str = "resources") -> str:
    return registry.resource_doc(provider_source, resource_type, category)


def _validate(files: List[TerraformFile], use_terraform: bool = True) -> str:
    ok, msg = checks.validate_terraform([TerraformFile.model_validate(f) for f in files], use_terraform)
    return ("OK: " if ok else "INVALID: ") + msg


def _scan(files: List[TerraformFile]) -> str:
    found = checks.scan_for_risky_patterns([TerraformFile.model_validate(f) for f in files])
    if not found:
        return "No risky patterns found."
    return json.dumps([f.model_dump() for f in found])


def registry_tools() -> List[StructuredTool]:
    return [
        StructuredTool.from_function(
            func=_safe(_search_providers), name="search_terraform_providers", args_schema=SearchProvidersArgs,
            description="Find Terraform providers for any cloud or vendor. Use first to resolve what a "
            "user-named cloud is called in Terraform (e.g. 'oracle' -> 'oracle/oci').",
        ),
        StructuredTool.from_function(
            func=_safe(_list_resources), name="list_provider_resources", args_schema=ListResourcesArgs,
            description="List a provider's resource types filtered by keyword. Use to translate a "
            "generic need ('managed postgres', 'object storage') into this cloud's own terms.",
        ),
        StructuredTool.from_function(
            func=_safe(_resource_doc), name="get_resource_doc", args_schema=ResourceDocArgs,
            description="Read the official docs for one resource type: required arguments, example, attributes. "
            "Read it before writing that resource.",
        ),
    ]


def validate_tool(use_terraform: bool = True) -> StructuredTool:
    return StructuredTool.from_function(
        func=_safe(lambda files: _validate(files, use_terraform)), name="validate_terraform", args_schema=FilesArgs,
        description="Validate Terraform files (syntax, and provider schema when terraform is installed). "
        "Call after writing; fix every reported error and call again.",
    )


def scan_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=_safe(_scan), name="scan_for_risky_patterns", args_schema=FilesArgs,
        description="Cloud-neutral scan for hard-coded secrets, 0.0.0.0/0 exposure, public access and disabled encryption.",
    )
