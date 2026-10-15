"""A/B benchmark harness: no harness vs Gravitas vs Veratum on identical tasks."""
import os

BENCH_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKS_DIR = os.path.join(BENCH_ROOT, "tasks")
RESULTS_DIR = os.path.join(BENCH_ROOT, "results")
CACHE_DIR = os.path.join(BENCH_ROOT, ".cache")
VERATUM_ROOT = os.path.dirname(BENCH_ROOT)
