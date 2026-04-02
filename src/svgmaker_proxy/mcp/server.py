from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from pydantic import BaseModel, Field

from svgmaker_proxy.bootstrap import ServiceContainer, build_services, initialize_services
from svgmaker_proxy.core.config import Settings, get_settings
from svgmaker_proxy.core.logging import configure_logging
from svgmaker_proxy.models.generation import SvgmakerEditRequest, SvgmakerGenerateRequest


@dataclass(slots=True)
class McpAppContext:
    services: ServiceContainer


class McpGenerateResult(BaseModel):
    generation_id: str | None = None
    svg_url: str | None = None
    svg_text: str | None = None


class McpGeneratePublicResult(BaseModel):
    generation_id: str | None = None
    svg_url: str | None = None


class McpEditResult(BaseModel):
    generation_id: str | None = None
    svg_url: str | None = None
    svg_text: str | None = None


class McpEditPublicResult(BaseModel):
    generation_id: str | None = None
    svg_url: str | None = None


_shared_services: ServiceContainer | None = None


def _get_services_from_context(
    ctx: Context[ServerSession, McpAppContext] | None,
) -> ServiceContainer:
    if _shared_services is not None:
        return _shared_services
    if ctx is None:
        raise RuntimeError("MCP services are not initialized")
    return ctx.request_context.lifespan_context.services


async def _report_start(
    ctx: Context[ServerSession, McpAppContext] | None,
    message: str,
) -> None:
    if ctx is not None:
        await ctx.info(message)
        await ctx.report_progress(progress=0.1, total=1.0, message="Preparing request")


async def _report_done(
    ctx: Context[ServerSession, McpAppContext] | None,
    message: str,
) -> None:
    if ctx is not None:
        await ctx.report_progress(progress=1.0, total=1.0, message=message)


async def _generate_svg(
    *,
    prompt: str,
    quality: str,
    aspect_ratio: str,
    background: str,
    ctx: Context[ServerSession, McpAppContext] | None,
):
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise ValueError("prompt must not be empty")

    await _report_start(ctx, "Starting SVG generation")
    services_for_request = _get_services_from_context(ctx)
    result = await services_for_request.generation_proxy.generate(
        SvgmakerGenerateRequest(
            prompt=normalized_prompt,
            quality=quality,
            aspect_ratio=aspect_ratio,
            background=background,
            stream=True,
            base64_png=False,
            svg_text=True,
            style_params={},
        )
    )

    svg_text = result.raw_payload.get("svgText")
    if svg_text is not None and not isinstance(svg_text, str):
        svg_text = None
    return result, svg_text


async def _edit_svg(
    *,
    prompt: str,
    source_svg_text: str | None,
    source_file_text: str | None,
    source_filename: str | None,
    quality: str,
    aspect_ratio: str,
    background: str,
    ctx: Context[ServerSession, McpAppContext] | None,
):
    normalized_prompt = prompt.strip()
    normalized_svg_text = source_svg_text.strip() if source_svg_text else None
    normalized_file_text = source_file_text.strip() if source_file_text else None

    if not normalized_prompt:
        raise ValueError("prompt must not be empty")
    if bool(normalized_svg_text) == bool(normalized_file_text):
        raise ValueError("Provide exactly one source: source_svg_text or source_file_text")

    await _report_start(ctx, "Starting SVG edit")
    services_for_request = _get_services_from_context(ctx)
    result = await services_for_request.generation_proxy.edit(
        SvgmakerEditRequest(
            prompt=normalized_prompt,
            quality=quality,
            aspect_ratio=aspect_ratio,
            background=background,
            stream=True,
            svg_text=True,
            source_svg_text=normalized_svg_text,
            source_file_content=normalized_file_text.encode("utf-8")
            if normalized_file_text
            else None,
            source_filename=source_filename,
            source_content_type="image/svg+xml" if normalized_file_text else None,
        )
    )

    svg_text = result.raw_payload.get("svgText")
    if svg_text is not None and not isinstance(svg_text, str):
        svg_text = None
    return result, svg_text


def create_mcp_server(
    *,
    services: ServiceContainer | None = None,
    settings: Settings | None = None,
    streamable_http_path: str = "/mcp",
) -> FastMCP:
    global _shared_services
    _shared_services = services

    app_settings = settings or get_settings()

    @asynccontextmanager
    async def mcp_lifespan(_: FastMCP) -> AsyncIterator[McpAppContext]:
        if services is not None:
            yield McpAppContext(services=services)
            return

        local_services = build_services()
        configure_logging(app_settings.log_level)
        await initialize_services(local_services)
        try:
            yield McpAppContext(services=local_services)
        finally:
            await local_services.database.dispose()

    mcp = FastMCP(
        "SVGMaker Proxy",
        instructions=(
            "Use this server to generate and edit SVG images. "
            "Prefer link tools unless raw svg_text is explicitly needed. "
            "Internal account routing, retries, and balance handling are hidden."
        ),
        lifespan=mcp_lifespan,
        json_response=True,
        stateless_http=True,
        streamable_http_path=streamable_http_path,
        log_level=app_settings.log_level,
    )

    @mcp.tool()
    async def svgmaker_generate(
        prompt: str = Field(description="Detailed prompt describing the SVG to generate."),
        quality: str = Field(
            default="high",
            description="Generation quality: low, medium, or high.",
        ),
        aspect_ratio: str = Field(
            default="auto",
            description="Aspect ratio such as auto, square, portrait, or landscape.",
        ),
        background: str = Field(
            default="auto",
            description="Background mode such as auto, transparent, or opaque.",
        ),
        ctx: Context[ServerSession, McpAppContext] | None = None,
    ) -> McpGenerateResult:
        """Generate SVG and return raw svg_text together with the resulting link."""
        result, svg_text = await _generate_svg(
            prompt=prompt,
            quality=quality,
            aspect_ratio=aspect_ratio,
            background=background,
            ctx=ctx,
        )
        await _report_done(ctx, "SVG generation complete")
        return McpGenerateResult(
            generation_id=result.generation_id,
            svg_url=result.svg_url,
            svg_text=svg_text,
        )

    @mcp.tool()
    async def svgmaker_generate_link(
        prompt: str = Field(description="Detailed prompt describing the SVG to generate."),
        quality: str = Field(
            default="high",
            description="Generation quality: low, medium, or high.",
        ),
        aspect_ratio: str = Field(
            default="auto",
            description="Aspect ratio such as auto, square, portrait, or landscape.",
        ),
        background: str = Field(
            default="auto",
            description="Background mode such as auto, transparent, or opaque.",
        ),
        ctx: Context[ServerSession, McpAppContext] | None = None,
    ) -> McpGeneratePublicResult:
        """Generate SVG and return only lightweight link-based fields."""
        result, _ = await _generate_svg(
            prompt=prompt,
            quality=quality,
            aspect_ratio=aspect_ratio,
            background=background,
            ctx=ctx,
        )
        await _report_done(ctx, "SVG generation complete")
        return McpGeneratePublicResult(
            generation_id=result.generation_id,
            svg_url=result.svg_url,
        )

    @mcp.tool()
    async def svgmaker_edit(
        prompt: str = Field(description="Instructions describing how to edit the SVG."),
        source_svg_text: str | None = Field(
            default=None,
            description="Existing SVG markup to edit. Provide this or source_file_text.",
        ),
        source_file_text: str | None = Field(
            default=None,
            description="Existing SVG file content to edit. Provide this or source_svg_text.",
        ),
        source_filename: str | None = Field(
            default=None,
            description="Optional filename to associate with source_file_text.",
        ),
        quality: str = Field(
            default="high",
            description="Edit quality: low, medium, or high.",
        ),
        aspect_ratio: str = Field(
            default="auto",
            description="Aspect ratio such as auto, square, portrait, or landscape.",
        ),
        background: str = Field(
            default="auto",
            description="Background mode such as auto, transparent, or opaque.",
        ),
        ctx: Context[ServerSession, McpAppContext] | None = None,
    ) -> McpEditResult:
        """Edit an SVG and return raw svg_text together with the resulting link."""
        result, svg_text = await _edit_svg(
            prompt=prompt,
            source_svg_text=source_svg_text,
            source_file_text=source_file_text,
            source_filename=source_filename,
            quality=quality,
            aspect_ratio=aspect_ratio,
            background=background,
            ctx=ctx,
        )
        await _report_done(ctx, "SVG edit complete")
        return McpEditResult(
            generation_id=result.generation_id,
            svg_url=result.svg_url,
            svg_text=svg_text,
        )

    @mcp.tool()
    async def svgmaker_edit_link(
        prompt: str = Field(description="Instructions describing how to edit the SVG."),
        source_svg_text: str | None = Field(
            default=None,
            description="Existing SVG markup to edit. Provide this or source_file_text.",
        ),
        source_file_text: str | None = Field(
            default=None,
            description="Existing SVG file content to edit. Provide this or source_svg_text.",
        ),
        source_filename: str | None = Field(
            default=None,
            description="Optional filename to associate with source_file_text.",
        ),
        quality: str = Field(
            default="high",
            description="Edit quality: low, medium, or high.",
        ),
        aspect_ratio: str = Field(
            default="auto",
            description="Aspect ratio such as auto, square, portrait, or landscape.",
        ),
        background: str = Field(
            default="auto",
            description="Background mode such as auto, transparent, or opaque.",
        ),
        ctx: Context[ServerSession, McpAppContext] | None = None,
    ) -> McpEditPublicResult:
        """Edit an SVG and return only lightweight link-based fields."""
        result, _ = await _edit_svg(
            prompt=prompt,
            source_svg_text=source_svg_text,
            source_file_text=source_file_text,
            source_filename=source_filename,
            quality=quality,
            aspect_ratio=aspect_ratio,
            background=background,
            ctx=ctx,
        )
        await _report_done(ctx, "SVG edit complete")
        return McpEditPublicResult(
            generation_id=result.generation_id,
            svg_url=result.svg_url,
        )

    return mcp


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    create_mcp_server(settings=settings).run()


if __name__ == "__main__":
    main()
