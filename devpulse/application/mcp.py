"""Application service for handling Model Context Protocol (MCP) tool and resource requests."""

import json
from pathlib import Path
from typing import Any, Callable

from ..domain.checks import check_python
from ..domain.hardware import HardwareProfile, ModelCatalog, rate_models
from ..domain.mcp import (
    MCP_PROTOCOL_VERSION,
    MCP_RESOURCES,
    MCP_SERVER_INFO,
    MCP_TOOLS,
    McpRequest,
    McpResponse,
)
from ..domain.models import Config
from ..domain.privacy import Vault


class McpServer:
    def __init__(
        self,
        root: Path,
        engine_factory: Callable[[], Any] | None = None,
        memory_index_factory: Callable[[], Any] | None = None,
        hardware_prober: Callable[[], HardwareProfile] | None = None,
        config_reader: Callable[[], Config] | None = None,
    ):
        self.root = root
        self.engine_factory = engine_factory
        self.memory_index_factory = memory_index_factory
        self.hardware_prober = hardware_prober
        self.config_reader = config_reader

    def handle_request(self, req: McpRequest) -> McpResponse:
        method = req.method
        if method == 'initialize':
            return McpResponse(
                id=req.id,
                result={
                    'protocolVersion': MCP_PROTOCOL_VERSION,
                    'capabilities': {
                        'tools': {},
                        'resources': {},
                        'prompts': {},
                    },
                    'serverInfo': MCP_SERVER_INFO,
                },
            )
        elif method == 'notifications/initialized':
            return McpResponse(id=req.id, result=None)
        elif method == 'ping':
            return McpResponse(id=req.id, result={})
        elif method == 'tools/list':
            return McpResponse(id=req.id, result={'tools': MCP_TOOLS})
        elif method == 'tools/call':
            return self._handle_tool_call(req)
        elif method == 'resources/list':
            return McpResponse(id=req.id, result={'resources': MCP_RESOURCES})
        elif method == 'resources/read':
            return self._handle_resource_read(req)
        else:
            return McpResponse(
                id=req.id,
                error={'code': -32601, 'message': f'Method not found: {method}'},
            )

    def _handle_tool_call(self, req: McpRequest) -> McpResponse:
        name = req.params.get('name')
        args = req.params.get('arguments') or {}

        try:
            if name == 'devpulse_verify':
                out = self._tool_verify(args)
            elif name == 'devpulse_review':
                out = self._tool_review(args)
            elif name == 'devpulse_search_memory':
                out = self._tool_search_memory(args)
            elif name == 'devpulse_hardware_profile':
                out = self._tool_hardware_profile(args)
            else:
                return McpResponse(
                    id=req.id,
                    error={'code': -32601, 'message': f'Unknown tool: {name}'},
                )
            return McpResponse(
                id=req.id,
                result={'content': [{'type': 'text', 'text': json.dumps(out, indent=2)}]},
            )
        except Exception as exc:
            return McpResponse(
                id=req.id,
                result={
                    'content': [{'type': 'text', 'text': f'Error executing {name}: {str(exc)}'}],
                    'isError': True,
                },
            )

    def _tool_verify(self, args: dict[str, Any]) -> dict[str, Any]:
        code = args.get('code', '')
        file_path = args.get('file', 'stdin.py')

        vault = Vault()
        vault.scrub(code)

        errors = []
        if vault.count > 0:
            errors.append(
                {
                    'rule': 'secret-leak',
                    'severity': 'error',
                    'message': f'Secret detected ({vault.count} pattern(s)).',
                    'path': file_path,
                    'line': 1,
                }
            )

        findings = check_python([{'path': file_path, 'content': code}])
        for f in findings:
            if f['severity'] == 'error':
                errors.append(f)

        if errors:
            return {'status': 'failed', 'errors': errors}
        return {'status': 'clean'}

    def _tool_review(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.engine_factory or not self.config_reader:
            return {'summary': 'Review engine not configured.', 'findings': []}
        engine = self.engine_factory()
        config = self.config_reader()
        res = engine.review(
            self.root,
            config,
            mode=args.get('mode', 'offline'),
            file=args.get('file'),
            worktree=args.get('worktree', False),
        )
        return res

    def _tool_search_memory(self, args: dict[str, Any]) -> dict[str, Any]:
        query = args.get('query', '')
        limit = args.get('limit', 8)
        if not self.memory_index_factory:
            return {'results': []}
        index = self.memory_index_factory()
        vault = Vault()
        chunks = index.search(self.root, vault, query, limit=limit)
        return {
            'query': query,
            'results': [
                {
                    'source': c.source_path,
                    'kind': c.kind,
                    'lines': f'{c.line_start}-{c.line_end}',
                    'text': c.text,
                }
                for c in chunks
            ],
        }

    def _tool_hardware_profile(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.hardware_prober:
            profile = HardwareProfile(
                total_ram_bytes=8 * 1024**3,
                available_ram_bytes=4 * 1024**3,
                vram_bytes=0,
                gpu_name='Unknown',
                os_name='Unknown',
            )
        else:
            profile = self.hardware_prober()

        catalog = ModelCatalog.default_models()
        ratings = rate_models(profile, catalog)
        return {
            'hardware': {
                'os': profile.os_name,
                'ram_total_gb': round(profile.total_ram_gb, 2),
                'ram_available_gb': round(profile.available_ram_gb, 2),
                'gpu': profile.gpu_name,
                'vram_gb': round(profile.vram_gb, 2),
            },
            'top_recommended_model': ratings[0].spec.name if ratings else None,
            'ratings': [
                {
                    'model': r.spec.name,
                    'tier': r.tier.value,
                    'predicted_tps': r.predicted_tps,
                    'coding_iq': r.spec.coding_iq,
                    'recommendation_score': r.recommendation_score,
                }
                for r in ratings[:5]
            ],
        }

    def _handle_resource_read(self, req: McpRequest) -> McpResponse:
        uri = req.params.get('uri', '')
        text = ''
        if uri == 'devpulse://rules':
            rules_path = self.root / '.devpulse/RULES.md'
            if rules_path.is_file():
                text = rules_path.read_text(encoding='utf-8', errors='replace')
        elif uri == 'devpulse://memory':
            mem_path = self.root / '.devpulse/MEMORY.md'
            if mem_path.is_file():
                text = mem_path.read_text(encoding='utf-8', errors='replace')
        else:
            return McpResponse(
                id=req.id,
                error={'code': -32602, 'message': f'Resource not found: {uri}'},
            )
        return McpResponse(
            id=req.id,
            result={'contents': [{'uri': uri, 'mimeType': 'text/markdown', 'text': text}]},
        )
