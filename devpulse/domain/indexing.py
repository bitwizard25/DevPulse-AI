"""Content types and access decisions for the derived project index."""

from dataclasses import dataclass
from pathlib import PurePath

CODE_SUFFIXES = frozenset(
    {
        '.py',
        '.pyi',
        '.ipynb',
        '.js',
        '.jsx',
        '.mjs',
        '.cjs',
        '.ts',
        '.tsx',
        '.go',
        '.rs',
        '.java',
        '.kt',
        '.kts',
        '.scala',
        '.swift',
        '.m',
        '.mm',
        '.c',
        '.h',
        '.cc',
        '.cpp',
        '.hpp',
        '.cxx',
        '.cs',
        '.fs',
        '.fsx',
        '.vb',
        '.rb',
        '.php',
        '.phtml',
        '.ex',
        '.exs',
        '.erl',
        '.hrl',
        '.hs',
        '.lua',
        '.r',
        '.jl',
        '.dart',
        '.vue',
        '.svelte',
        '.html',
        '.css',
        '.scss',
        '.sass',
        '.less',
        '.sql',
        '.graphql',
        '.proto',
        '.sh',
        '.bash',
        '.ps1',
        '.psm1',
        '.bat',
        '.cmd',
        '.md',
        '.mdx',
        '.rst',
        '.tf',
        '.tfvars',
        '.cmake',
        '.yaml',
        '.yml',
    }
)
CONFIG_SUFFIXES = frozenset({'.json', '.toml', '.ini', '.cfg', '.xml', '.properties'})
PROJECT_MARKERS = frozenset(
    {
        'pyproject.toml',
        'setup.py',
        'setup.cfg',
        'requirements.txt',
        'package.json',
        'cargo.toml',
        'go.mod',
        'gemfile',
        'composer.json',
        'pom.xml',
        'build.gradle',
        'cmakelists.txt',
        'makefile',
        'dockerfile',
        'justfile',
        'deno.json',
    }
)


def is_coding_path(name: str) -> bool:
    path = PurePath(name)
    return path.suffix.lower() in CODE_SUFFIXES or path.name.lower() in PROJECT_MARKERS


def is_indexable_path(name: str) -> bool:
    return is_coding_path(name) or PurePath(name).suffix.lower() in CONFIG_SUFFIXES


@dataclass(frozen=True)
class ProjectInspection:
    is_git: bool
    has_coding_files: bool
    complete: bool = True


@dataclass(frozen=True)
class IndexDecision:
    status: str
    reason: str
    is_git: bool
