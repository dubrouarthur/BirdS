"""Teacher-generated SFT data for Bird (scenario sampler, teacher prompts, converter, validator, runner).

specs.py     seeded scenario sampler (structured briefs, no LLM)
prompts.py   teacher prompts, JSON schemas and hand-written gold examples
convert.py   teacher JSON -> unified record (birds.schema)
validate.py  deterministic acceptance filter
runner.py    async driver for any OpenAI-compatible endpoint (resumable, chunked output, stats)
"""

SOURCE = "bird_synth"
LICENSE = "apache-2.0"
