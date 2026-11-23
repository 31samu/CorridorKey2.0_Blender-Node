# Performance measurements

## Apple M1 Pro · 16 GB unified memory

### Standard 720p Blender benchmark

Blender 5.3.0, source frames 17–32 of `pink-outfit-720p.mp4`, at 25 fps in the scene compositor. The working canvas was 1280 × 720 and both backends padded to 1280 × 768. Despill was 0.5 with no alpha hint or garbage mask.

| Build | Time awareness in Stage 1 | Median Analyze | Time per frame | Median backend wall time | Peak backend footprint |
| --- | --- | ---: | ---: | ---: | ---: |
| MLX 0.4.0 · mixed FP16 | No · 1 frame, stride 1 | 29.23 s | 1.83 s | 26.48 s | 3.93 GiB |
| MPS 0.5.1 · mixed BF16 | No · 1 frame, stride 1 | 98.42 s | 6.15 s | 95.86 s | 7.41 GiB |
| MPS 0.5.1 · mixed BF16 | Yes · 4 frames, stride 2 | 98.43 s | 6.15 s | 93.86 s | 7.46 GiB |
| MPS 0.5.1 · mixed BF16 with native MPSGraph attention | No · 1 frame, stride 1 | 85.69 s | 5.36 s | 83.30 s | 7.41 GiB |
| MPS 0.5.2 · mixed BF16 with Larger Batches | No · 1 frame, stride 1 | 85.45 s | 5.34 s | 82.97 s | 7.42 GiB |
| MPS 0.5.2 · mixed BF16 with Larger Batches and native MPSGraph attention | No · 1 frame, stride 1 | 80.61 s | 5.04 s | 78.30 s | 7.41 GiB |

Stock single-frame MPS took 3.37× as long as MLX in Blender. Four-frame MPS took effectively the same time as single-frame MPS on this clip. Native MPSGraph attention cut single-frame Analyze time by 12.9% with the same peak footprint to two decimal places.

In 0.5.2, Larger Batches reduced the single-frame median by 13.2% from the stock 0.5.1 run. Both options together reduced it by 18.1%. The fastest MPS run configuration still took 2.76× as long as MLX. The 0.5.2 runs used the same benchmark in a separate session. The warm-ups took 114.88 s with Larger Batches and 124.22 s with both options.

Each median uses three timed bakes after one warm-up. Backend wall time includes model loading and output writes. Peak backend footprint is the highest macOS `time -l` peak memory footprint among the three timed backend processes. MLX wrote cutout, despilled foreground, and raw foreground as 16-bit PNGs. MPS used PyTorch 2.9.1 and wrote cutout and raw foreground as EXRs. The MLX backend reports its 24 fps default for PNG sequences even though the Blender scene ran at 25 fps. All comparisons use the same numbered source frames.

The optional MPSGraph kernel was built in a scratch checkout with the same model files and batch sizes as stock single-frame MPS. All four bakes completed and logged that native attention was enabled. The logs also printed `Failed to import MPS module`. In the two median-time single-frame runs, the absolute alpha difference averaged 0.00035 on a 0–1 scale. About 0.026% of pixels differed by more than 0.10.

The 0.5.2 preset raised full-attention query chunks from 128 to 512 tokens, Swin batches from 1 to 4, and MLP chunks from 4,096 to 16,384 tokens. Compared with the median stock MPS run, mean absolute alpha differences were 0.00021 with Larger Batches and 0.00038 with both options. One pixel differed by more than 0.10 with Larger Batches alone. With both options, 0.029% of pixels exceeded that threshold.

### Earlier measurements

| Build and workflow | Working canvas | Time awareness in Stage 1 | Frames | Total time | Time per frame | Peak process memory |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| MLX 0.4.0 · CLI | 1280 × 720 | No · single frame | 8 | 12.20 s | 1.53 s | 3.97 GiB |
| MLX 0.4.0 · CLI | 1536 × 1024 | No · single frame | 8 | 19.73 s | 2.47 s | 4.16 GiB |
| MPS 0.5.1 · Blender scene compositor | 256 × 144 | No · single frame | 4 | 27.20 s | 6.80 s | Unmeasured |
| MPS 0.5.1 · Blender Sequencer strip | 256 × 144 | Yes · four frames | 4 | 51.38 s | 12.85 s | Unmeasured |

Single-frame windows advance one frame at a time. Four-frame windows advance two frames at a time. This column describes whether Stage 1 processes frames together. Both MPS runs also used the separate RVM prepass, which carries information across frames.

**Direct comparison.** On the same eight-frame clip, the larger MLX canvas took **62% longer** and used **0.19 GiB** more peak process memory. The MPS rows are single runs with different footage and settings. A direct MLX versus MPS comparison would require matching footage, resolution, outputs, and timing scope.

#### How the earlier timings were measured

- **MLX CLI.** Median of three runs after one warm-up. Both profiles used mixed FP16, custom MLX kernels, and single-frame Stage 2. The model sizes after padding were 1280 × 768 and 1536 × 1024. For the larger run, the 1280 × 720 source was upscaled to 1536 × 864 and fitted inside the larger canvas. Timing starts at decoding and ends after export and scratch cleanup. Blender plate baking and model loading are outside that interval. Each run wrote three 16-bit PNG sequences for cutout, despilled foreground, and raw foreground. Peak memory is the highest process footprint sampled every 20 ms across the three measured runs.
- **MPS Blender Analyze.** PyTorch 2.9.1 on MPS padded the working canvas to 256 × 256. Timing includes plate baking, model loading, inference, EXR export, and loading the output back into Blender. Both runs wrote cutout and raw foreground. The Sequencer run also fitted the strip, restored its original dimensions after keying, and used a first-frame alpha hint.

### Standard test for future runs

1. Use source frames 17–32 of `test-footage/pink-outfit-720p.mp4`, counting the first source frame as 1. Bake in the Blender scene compositor at 1280 × 720 and 100% scale. Keep the source placement, frame rate, and render settings the same. Leave the alpha hint and garbage mask disconnected and set despill strength to 0.5.
2. Use single-frame Stage 1 with a stride of one for the baseline. To test four-frame time awareness, repeat the MPS run with a four-frame window and stride of two. To test native MPSGraph attention, repeat the same MPS configuration with the kernel enabled and keep the batch sizes fixed.
3. Run one warm-up and three measured bakes per configuration, with a fresh output cache for each bake. Time **Analyze** from click to result available. If measuring backend time separately, record the interval explicitly. Record the median, seconds per frame, peak backend process memory if sampled, and the Blender and backend versions.
4. Record the padded model dimensions, precision, and output files. The stock builds write different formats and passes, so their **Analyze** times compare the full Blender workflows. For an inference-only comparison, use timings that exclude model loading and output encoding on both runs.
