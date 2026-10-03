# Future plan: plain-language recording search

Steps 1 and 2 are in the hub. Step 3 waits for continuous recording on an NVMe drive. Do not start step 3 until it is asked for.

## What exists

An event is a time, a label (`person`, `doorbell`, `driveway`, `photo`, `clip`), a confidence, a snapshot, and sometimes a short Talk clip. There is no 24/7 archive, no caption, and no search index. The live neural processor detects a person. Other classes from that model are discarded.

## What this plan adds

A question in ordinary language returns the matching events, and later the matching minute of video.

Build it in this order:

1. Done. `GET /v1/events/search?q=` turns a sentence into a time range, camera, and label, then queries the event table. Example: "person at the door yesterday afternoon."
2. Done. A confirmed bicycle, car, motorbike, bus, truck, bird, cat, dog, backpack, or suitcase is stored with its camera. It does not raise the door alarm. Example: "car in the driveway Sunday."
3. Waiting. After 24/7 recording exists on the NVMe, caption or embed a few keyframes per minute in the background and search that text. Example: "delivery driver on Sunday afternoon," then play that minute.

## Limits

- Do the first two before the third. The third waits on continuous recording.
- A question parser writes a filter. It does not watch video.
- Caption or embed frames later, off the live camera path. Do not run that work on every frame, and do not stall person detection.
- Keep it local. No cloud model answers the question or stores the footage.
- "Delivery driver" is a caption of a saved frame. The live person model cannot produce that label.
