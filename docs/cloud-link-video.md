# Live camera traffic and what it costs

The Live Cameras card sends JPEG frames only while it is on screen. Cloud Link does not upload the camera to Aliyun by itself. The always-on piece is a small outbound tunnel so a phone away from home can open that card later.

One card shows one camera, the tab that is selected. The hub encodes each frame in `hub/media/live.py`: width at most 640 pixels, JPEG quality 60, about 10 frames a second. The iOS card opens the socket in `ios-app/src/components/CameraLive.tsx` and closes it when the card unmounts.

| Camera | Socket |
|---|---|
| Front door | `/v1/system/live` |
| Driveway | `/v1/driveway/live` |

## Path

**Phone on the home LAN, or on Tailscale.** The phone opens the socket straight to the ROCK. Frames go hub to phone. Aliyun is not on the path, and the cellular network is not either when the phone is on Wi-Fi.

**Phone away from home, using Cloud Link.** The hub has already dialed Aliyun. The phone opens `wss://rock.link.yaojiabuy.com/.../live`. The relay on `8.129.103.161` splices that TLS connection to the hub and does not decode the frames.

1. The hub encodes a JPEG and writes it to the socket.
2. Those bytes travel hub to Aliyun. That direction is inbound to the server.
3. Aliyun forwards the same bytes to the phone. That direction is outbound from the server.
4. The phone’s replies are small: they keep the socket alive. They are not another copy of the video.

Closing the card, or the phone suspending the app, closes the socket. Frames stop. A second phone on the same card is a second copy of the same stream.

WebRTC talk is a different path. It is not what this card sends, and TURN is not required for these JPEG frames.

## A full day with the card left open

One phone, one camera, 24 hours, screen staying on the card:

| Quantity | Estimate |
|---|---|
| Frame rate | 10 per second, 640 px wide, JPEG quality 60 |
| Outbound volume | about 15–35 GB |
| Steady rate | about 2–4 Mbps |

A plain scene, such as a close lamp, is the low end. A detailed driveway is the high end. The range is an estimate from those encoder settings, not a measured bill.

## Aliyun

The trial server is in 华南1（深圳）. Aliyun bills **outbound** public traffic. Inbound traffic, including the hub’s upload into the server, is not billed. List price for Shenzhen outbound on a pay-by-traffic public IP is **0.80 yuan per GB**.

For the day above, outbound is about 15–35 GB, so the traffic charge is about **12–28 yuan**. A second phone adds another 15–35 GB.

If that public IP is on a **fixed bandwidth** plan, there is no per-GB charge. The plan’s cap has to be at least about 3 Mbps, or the picture cannot stay at 10 frames a second. If the account uses Cloud Data Transfer (CDT), a small mainland monthly allowance may apply and the price after that can differ from 0.80 yuan/GB. The bill line is ECS public traffic, or 云数据传输 if CDT is on.

## Cellular carrier

The phone downloads the same 15–35 GB. Upload is about 1 GB more, for the replies on that socket. Wi-Fi away from home still uses Cloud Link, and Aliyun still bills the outbound frames, but the carrier does not count those bytes.

There is no single per-GB carrier price:

- On a current US unlimited plan this is usually no extra charge. It does use a large part of the month’s high-speed allotment. Many plans slow the line after about 50–100 GB instead of adding a fee.
- On a metered or prepaid plan, the charge is that plan’s price times 15–35 GB.
- While roaming, the same 15–35 GB is often billed per GB and can cost more than the Aliyun traffic.

If the phone locks and the system suspends the app, the socket closes and both charges stop.
