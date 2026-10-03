// Elegoo Mega 2560 R3 siren and LED for the home hub.
// This board has no Wi-Fi. The PC opens the USB serial port and sends one
// line per action: "ON" or "OFF". The burst stops by itself so a missed
// OFF cannot leave the buzzer running.
//
// Pin 8 is the LED (steady on). Pin 9 is the buzzer (880 Hz tone).
// Both return to the pin labeled GND. The onboard LED on pin 13 follows
// the same burst.

const int kLedPin = 8;
const int kBuzzerPin = 9;
const int kOnboardLed = 13;
const unsigned long kBurstMs = 4000;

unsigned long burstUntil = 0;
String line;

void setup() {
  pinMode(kLedPin, OUTPUT);
  pinMode(kBuzzerPin, OUTPUT);
  pinMode(kOnboardLed, OUTPUT);
  digitalWrite(kLedPin, LOW);
  digitalWrite(kBuzzerPin, LOW);
  digitalWrite(kOnboardLed, LOW);
  Serial.begin(9600);
}

void loop() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      handleLine();
      line = "";
    } else if (line.length() < 16) {
      line += c;
    }
  }

  bool on = burstUntil != 0 && millis() < burstUntil;
  if (!on) {
    burstUntil = 0;
    noTone(kBuzzerPin);
  } else {
    tone(kBuzzerPin, 880);
  }
  digitalWrite(kLedPin, on ? HIGH : LOW);
  digitalWrite(kOnboardLed, on ? HIGH : LOW);
}

void handleLine() {
  line.trim();
  if (line == "ON") {
    burstUntil = millis() + kBurstMs;
    Serial.println("ok");
  } else if (line == "OFF") {
    burstUntil = 0;
    Serial.println("ok");
  }
}
