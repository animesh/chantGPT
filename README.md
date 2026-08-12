## Bhagavad Gita (भगवद्गीता)

[#bhagavad-gita](#bhagavad-gita)

A representative shard covering all 18 chapters is in `examples/bhagavad_gita_shard.json`.
The full 700-verse shard can be generated with `scripts/generate_bg_shard.py`.

### Render sample verses

```bash
# render the 22 representative verses (all 18 chapters sampled):
python src/render.py \
  --shard examples/bhagavad_gita_shard.json \
  --results /tmp/bg_results.json \
  --outdir out/bhagavad_gita/
mkdir -p out/bhagavad_gita
export PYTHONPATH="$PWD/BigVGAN:$PWD/src:$PYTHONPATH"
python src/render.py --shard examples/bhagavad_gita_shard.json \
  --results bg_results.json --outdir out/bhagavad_gita/
```

### Build and render the full 700-verse text

```bash
python -m venv chantGPT
source chantGPT/bin/activate #source .venv/bin/activate
pip install torch==2.6.0+cu124 torchaudio==2.6.0+cu124 \
  --index-url https://download.pytorch.org/whl/cu124 \
  --force-reinstall
export PYTHONPATH="$PWD/BigVGAN:$PWD/src:$PYTHONPATH"
python src/render.py --shard examples/bhagavad_gita_shard.json \
  --results bg_results.json --outdir out/bhagavad_gita/
mkdir -p out/bhagavad_gita_full
python src/render.py   --shard examples/bhagavad_gita_full_shard.json   --results bg_full_results.json   --outdir out/bhagavad_gita_full/
```

```bash
# 1. Generate the full shard (downloads GRETIL source automatically):
source .venv/bin/activate
python scripts/generate_bg_shard.py \
  --output examples/bhagavad_gita_full_shard.json

# 2. Render -- GPU recommended; ~700 wav files:
python src/render.py \
  --shard examples/bhagavad_gita_full_shard.json \
  --results /tmp/bg_full_results.json \
  --outdir out/bhagavad_gita_full/

# Render only chapter 2 (e.g. Sankhya Yoga):
python scripts/generate_bg_shard.py --chapters 2 \
  --output /tmp/bg_ch2.json
python src/render.py --shard /tmp/bg_ch2.json \
  --results /tmp/bg_ch2_results.json \
  --outdir out/bg_ch2/
```

### Meter notes

| Chapter(s) | Dominant meter | Padas | Syllables/pada |
|---|---|---|---|
| 1-10, 12-18 | Anushtubh (śloka) | 4 | 8 |
| 11 (Vishvarupa) | Trishtubh / Jagati | 4 | 11-12 |

Chapter 11's grand cosmic vision verses (`bg_11_*`) are in **trishtubh** -- the shard
sets `"meter": "trishtubh"` accordingly so Vagdhenu selects the right reference clip.

### Key verses included in the sample shard

| ID | Verse | Theme |
|---|---|---|
| bg_01_01 | 1.1 | Dhritarashtra's question on Kurukshetra |
| bg_02_19 | 2.19 | The indestructible Self |
| bg_02_47 | 2.47 | Karmanye vadhikaraste -- action without attachment |
| bg_04_07 | 4.7 | Yada yada hi dharmasya -- divine incarnation |
| bg_04_08 | 4.8 | Paritranaya sadhunam -- purpose of incarnation |
| bg_06_05 | 6.5 | Self as friend and enemy |
| bg_09_22 | 9.22 | Yoga-kshemam vahamy-aham -- divine provision |
| bg_11_32 | 11.32 | Kaloasmi -- I am time, destroyer of worlds |
| bg_18_66 | 18.66 | Sarva-dharman parityajya -- the final teaching |
