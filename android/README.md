# Android clients

Two application IDs, one Gradle project:

| Module | Application ID | Role |
|---|---|---|
| `:phone` | `com.homeai.security.phone` | Personal remote |
| `:station` | `com.homeai.security.station` | Indoor tablet monitor |
| `:shared` | library | HTTPS client, session, WebRTC |

Open this `android/` folder in Android Studio (Giraffe / Ladybug or newer, JDK 17). The first sync creates `gradle/wrapper/gradle-wrapper.jar` if it is missing. Then pick a device or emulator and run `phone` or `station`.

The hub must already be reachable over HTTPS. Trust the mkcert CA on the device (see [docs/setup.md](../docs/setup.md)).
