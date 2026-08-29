# foldback

Hear a sine fold back below Nyquist, and watch the anti-alias filter stop it.

Catalog task: `EDU-034`. One of a public catalog of build ideas:
https://github.com/JesseRWeigel/722-things-to-build

## What this is

One HTML file. Sweep a tone up past half your sample rate and listen to it turn around and come
back down. The spectrum plot shows where it landed, the fold map shows the zigzag it followed to
get there, and a button puts an anti-alias filter in front of the sampler so you can hear what
that changes and read how many decibels it bought.

It is live at https://jesserweigel.github.io/foldback/ and in this repository at
[`docs/index.html`](docs/index.html). Open it from a disk or serve it, both work.
No libraries, no CDN, no web fonts, no network of any kind. Web Audio and about a thousand lines
of JavaScript.

### The one line the whole thing is

A sine at frequency `f`, sampled at rate `fs`, gives exactly the same sequence of numbers as a
sine at

    alias(f, fs) = |f - round(f / fs) * fs|

Write `f` as `k*fs + r` with `k = round(f/fs)`, so `r` lands between `-fs/2` and `+fs/2`. Then
`sin(2*pi*f*n/fs) = sin(2*pi*k*n + 2*pi*r*n/fs) = sin(2*pi*r*n/fs)`, because `k` and `n` are whole
numbers and a whole number of turns is no turn at all. A negative `r` is the same tone upside
down, which is why the absolute value is there.

That formula is the lesson, so it is checked rather than asserted. 1264 frequencies across two
sample rates, from a fortieth of Nyquist up to 7.9 times it, are rendered into real samples,
transformed, and the peak compared against the formula. The worst disagreement over the whole
sweep is 0.014 of a bin. The bound the tests demand is a twentieth of a bin, which is about
seventy times tighter than the whole bin a demonstration would usually settle for.

### What the filter toggle actually buys

At 44100 Hz with the corner at nine tenths of Nyquist, measured as the ratio of two rendered
signals and confirmed three separate ways:

| tone | order 2 | order 4 | order 6 | order 8 |
|---|---|---|---|---|
| 1.5 x Nyquist | -9.7 dB | -18.5 dB | -27.6 dB | -36.8 dB |
| 2.5 x Nyquist | -19.1 dB | -38.1 dB | -57.1 dB | -76.2 dB |
| 3.4 x Nyquist | -25.8 dB | -51.6 dB | -77.4 dB | -103.2 dB |

The three routes to those numbers share nothing but their inputs. One renders the tone twice,
with and without the filter, and measures the amplitude at the alias frequency both times. One
evaluates the cascade's transfer function on the unit circle from its coefficients. The third, in
`scripts/check_independent.py`, uses the closed form for a Butterworth after a bilinear transform
and never sees a coefficient at all. They agree to 0.0000 dB.

The part a checkbox does not tell you is in the last column of the table on the page. A
Butterworth is three decibels down at its own corner and keeps falling, so a corner placed below
Nyquist takes real signal off the top of the audible band, and a steeper filter takes more of it.
There is no order that gives a wall at Nyquist and leaves the band underneath untouched.

### Two things the page has to get right that are easy to miss

**The sample rate is not the page's to choose.** `AudioContext` runs at whatever the device gave
the browser, commonly 44100 or 48000. The page reads it, prints it, and every number follows from
it. Nothing is hardcoded.

**An anti-alias filter has to sit before the sampler**, and Web Audio has nowhere to put one.
Once a tone has folded there is nothing left in the recording to separate it from a tone that was
always down there, so a filter applied afterwards removes the alias and the honest signal at that
pitch with the same hand. The page therefore generates the tone at eight times your sample rate,
runs the filter there, and keeps every eighth value. That is a model of sampling rather than
sampling itself, and it is honest up to four times your sample rate, which is where the slider
stops.

## Running it

Open `docs/index.html`. That is the whole deliverable.

To check it:

```bash
bash scripts/verify.sh
```

It needs `python3`, `node` and Chrome or Chromium. If any of the three is missing the script
fails and names the install command. None of them is optional: without node the page's own
JavaScript is never compared against the Python that the tests exercise, and without a browser
nothing here has been shown to run in one.

The pieces, each of which runs on its own:

```bash
python3 -m unittest discover -s tests -t .   # 127 unit tests
python3 scripts/parity.py                    # the page's JavaScript against the Python
python3 scripts/browser_check.py             # the published page in real headless Chrome
python3 scripts/check_independent.py         # the closed forms, importing nothing from the package
python3 scripts/measure.py                   # one deterministic block of numbers
python3 scripts/sabotage.py                  # 33 sabotages, three gates, a null control
python3 scripts/privacy_scan.py              # planted positives, clean negatives
python3 scripts/build_page.py --check        # the published page is a fresh build
```

## How it is checked

**The arithmetic lives in Python, where a test can reach it.** `foldback/` holds the fold, a
radix-2 transform, the Butterworth cascade and the oversampled sampler, all standard library.
The page carries one copy of the same formulas in JavaScript, and `scripts/parity.py` extracts
that copy from `page/index.html` between two markers, runs it under node, and compares 18305
values against the Python one at a time. It is the same text the page hands to `addModule` to
build its AudioWorklet, so there is exactly one copy of the JavaScript in the repository and this
runs it.

**The page is opened in a real browser.** A single unbalanced parenthesis stops an inline script
from ever executing, and every unit test still passes because they import modules rather than load
a page. `scripts/browser_check.py` launches its own headless Chrome, waits for the page's self
check, and then compares the numbers the page produced against `foldback.fold` in the checking
process rather than believing the page's own PASS. It drives both audio engines: an AudioWorklet
over http, and the ScriptProcessorNode fallback from a `file://` URL where a worklet module cannot
be fetched. It moves the frequency slider, presses the filter button, walks the order menu, and
requires each of those to change the numbers the page prints. It checks four viewport widths for
anything escaping the page, and refuses `overflow-x: hidden`, which hides that bug and blanks the
probe that finds it at the same time.

**The checker that recomputes is independent, and proves it.** `scripts/check_independent.py`
imports `math`, `cmath`, `ast`, `json`, `pathlib`, `re` and `sys`, and walks its own import graph
with `ast` before doing anything, refusing to run if any reachable import lands inside the
package. It gets the fold from a reflected remainder with no rounding in it, finds where a tone
really landed by scanning a naive single frequency transform across the band and refining with a
golden section search, with no FFT and no window and no interpolation anywhere in it, and gets the
filter from the analog Butterworth magnitude. It reads the numbers out of `docs/index.html`,
which is the artifact a reader opens, rather than out of the Python that produced them.

`scripts/probes/` holds 9 probes, each declaring on its first line whether it must be refused or
accepted. Seven reach the package and must be refused, including one that gets there through a
helper beside it and one that assembles the module name at runtime. Two must be accepted, and one
of those names the package three times in comments and strings without importing it, which is what
separates an `ast` walk from a grep.

**The sabotage suite breaks the code 33 ways.** A sabotage counts only if it applies, moves the
fingerprint that `scripts/measure.py` prints, and is then caught. A null control runs first: an
untouched copy of the tree in a differently named directory has to fingerprint identically, or the
measurement is tracking where the code lives rather than what it does and the whole run is void.
The anchors are required to appear exactly once in every file they name, because anchoring on text
that appears twice means the edit may land in a copy nothing runs.

The sabotages are the mistakes this subject actually invites: a floor where the formula needs a
round, a plus where it needs a minus, a missing absolute value, the fold taken about half the rate
instead of the whole of it, the filter moved to after the decimation where it becomes a tone
control, its state reset every block, every section given the same Q, the window dropped from the
transform, the peak read from the nearest bin with no interpolation, the transform run backwards.
Ten of them are in the page's JavaScript rather than the Python, applied to both copies of the page
so they cannot be caught trivially for being out of date. One is dormant by construction, a guard
that never fires on correct input, and it is held to the opposite and stricter requirement: the
fingerprint must not move and the unit suite must fail anyway.

Two of the checks here were widened because a sabotage survived them. Reversing the direction of
the transform conjugates it, and a real signal's conjugate spectrum has exactly the same
magnitudes, so a measurement of magnitudes alone could not see it and neither could a comparison
between the two languages that only looked at magnitudes. Both now carry the complex transform.

**Five claims turned out to be wrong when they were measured**, four in prose and one in the page
itself. They are listed below, along with what they say now.

## What the measurements corrected

**The sampler is not bit for bit the naive oscillator.** The first draft of `foldback/sampler.py`
said it was. The phase there is accumulated one internal step at a time, so its rounding error
grows with n, where evaluating `sin(2*pi*f*n/fs)` rounds once. Measured at 44100 on a tone at 1.5
times Nyquist over 4096 samples, 2049 of the 4096 values match to the last bit and the largest
disagreement is 8.3e-12. The test now pins a bound of 1e-9 rather than zero, and also requires
that not every value match, so the claim cannot rot back the other way.

**The peak finder is 0.016 of a bin off at worst, not "under a hundredth".** That figure was
written from the literature rather than from this implementation. Walking a tone across a full bin
in two hundred steps puts the worst error at an offset of 0.29 of a bin from a centre.

**And it is only that good away from the two ends.** Within about a bin of DC or of Nyquist the
tone sits on top of its own mirror image and the three bin fit is dragged sideways by half a bin.
Measured: 0.48 of a bin at one bin from an end, 0.023 at 1.5 bins, 0.005 at 2.5 bins. The alias
sweep splits its frequencies on the two bin line and counts how many fall on the loose side,
rather than quietly leaving them out.

**Four of twelve figures in the filter table were wrong** because they had been reasoned out from
the six decibels an octave rule instead of measured. The table is now a dict a test reads back
against a fresh measurement, and the prose version of it is read back too.

**The page could not tell an empty buffer from silence.** Before Play is pressed the scope buffer
is full of zeros, and the spectrum was normalising that against its own maximum, which drew a flat
line along the very top of the plot that reads as full scale noise at every frequency. The caption
under it said the sine was being sampled on its zero crossings, which is the explanation for a
degenerate frequency and had nothing to do with why the buffer was empty. The curve is now drawn
only once there is something to draw, and the caption has three cases: nothing has played, this
frequency really is silent, or here is where the peak landed. `scripts/browser_check.py` reads the
caption at page load and requires the first of the three.

**The silence at Nyquist is a knife edge and not a fade.** A test was written assuming the level
faded towards the boundary. It does not. One hertz below Nyquist a sine still reaches full
amplitude, because what you are looking at is a beat at the difference frequency and the window
holds fifteen whole beats of it. Only within about a hundredth of a hertz does the beat get longer
than the window. The silence at a degenerate frequency has no width at all, which is why
`is_degenerate` exists as a case rather than as a limit.

## Status

`bash scripts/verify.sh`, pasted from a real run:

```
== 1. python, node and a browser, and the standard library only
   python 3.12.3, node v24.13.0, Google Chrome 145.0.7632.45, standard library only
   PASS

== 2. unit tests
   Ran 127 tests
   OK
   PASS

== 3. the test count the README claims is the count that exists
   the runner ran 127, and every count claimed in the README agrees with it
   PASS

== 4. the alias arithmetic, over a sweep wide enough for the tolerance to mean something
   1264 frequencies across 2 sample rates, up to 7.90 times Nyquist, 1106 of them above it, 14 of them exactly on a fold boundary
   the tight bound is 0.05 of a bin, loosened to 0.5 within 2.0 bins of an end of the spectrum
   PASS

== 5. the filter toggle, in decibels, at every order the page offers
   1.5 x Nyquist:    -9.7 dB   -18.5 dB   -27.6 dB   -36.8 dB
   2.5 x Nyquist:   -19.1 dB   -38.1 dB   -57.1 dB   -76.2 dB
   3.4 x Nyquist:   -25.8 dB   -51.6 dB   -77.4 dB  -103.2 dB
   orders 2, 4, 6 and 8, at 44100 Hz with the corner at 0.9 of Nyquist
   PASS

== 6. the page's own javascript against the tested python, value by value
   18305 values compared between the page's JavaScript and the tested Python
     alias         worst 0.000e+00 at 44100 x 0.05, limit 1e-09
     amplitude     worst 6.661e-16 at 44100 x 5.3, limit 1e-12
     coefficients  worst 0.000e+00 at corner 0.8 order 2 b0, limit 1e-15
     degenerate    worst 0.000e+00 at 44100 x 0.05, limit 0e+00
     folds         worst 0.000e+00 at 44100 x 0.05, limit 0e+00
     peak          worst 0.000e+00 at 44100 x 0.3, limit 1e-06
     poleqs        worst 0.000e+00 at order 2 pole 0, limit 1e-15
     response      worst 2.576e-14 at corner 0.95 order 8 at 1 x Nyquist, limit 1e-12
     samples       worst 1.610e-15 at 48000 x 0.5 filter 1 sample 563, limit 1e-12
     spectrum      worst 2.220e-16 at bin 163, limit 1e-09
     transform     worst 4.441e-16 at bin 27 real part, limit 1e-12
     window        worst 5.551e-17 at hann 57, limit 1e-15
   the page and the tests are running the same arithmetic
   PASS

== 7. the published page is what a fresh build produces
   docs/index.html matches a fresh build, 46541 characters
   PASS

== 8. the page in real headless chrome, on both audio engines
     Google Chrome 145.0.7632.45
     AudioWorklet: 14 frequencies rendered, worst peak 0.081 Hz from the formula, 6 filter 
   measurements from -51.6 to -9.7 dB, 6 degenerate frequencies silent
     the toggle at 81585 Hz: 'nothing is filtered' becomes 'this tone is cut by -55.8 dB before 
   sampling'
     order 2, 4, 6, 8 at that tone: -27.9 dB, -55.8 dB, -83.6 dB, -111.5 dB
     over http: both canvases drew, each over 2000 coloured pixels
     console warning, not a failure: warning: Canvas2D: Multiple readback operations using 
   getImageData are faster with the willReadFrequently attribute set to true. See: 
   https://html.spec.whatwg.
     console warning, not a failure: warning: Canvas2D: Multiple readback operations using 
   getImageData are faster with the willReadFrequently attribute set to true. See: 
   https://html.spec.whatwg.
     ScriptProcessorNode: 14 frequencies rendered, worst peak 0.081 Hz from the formula, 6 filter 
   measurements from -51.6 to -9.7 dB, 6 degenerate frequencies silent
     from a file url: both canvases drew, each over 2000 coloured pixels
   the page runs in a real browser on both audio engines, and its numbers agree with the tested 
   Python
   PASS

== 9. the measurement is deterministic and does not track the working directory
   FINGERPRINT 4496f093d7390e0c574aeae118cda8df934f75b223f7a7d8767f1d4df5bc04c6
   identical across two runs here and from an untouched copy under another name
   PASS

== 10. the measurement carries nothing belonging to this machine
   231 lines of measurement, none of them this machine's
   PASS

== 11. independent recomputation, importing nothing from the package
   independence: this file's import graph reaches nothing inside the package
   the fold: 46 frequencies land inside the band, are unchanged by a whole sample rate, and mirror 
   about every multiple of it
   the published page: 20 alias rows, worst disagreement 0.000e+00 Hz
   the samples themselves: 18 tones located by a naive scan and a golden section search, worst 
   0.0027 Hz off, which is 0.0003 of a bin
   the boundaries: 8 multiples of Nyquist sample to silence, as a zero phase sine on its own zero 
   crossings must
   the filter: 6 attenuation figures re-derived from the analog Butterworth magnitude, worst 
   disagreement 0.0000 dB
   the cost: a corner below Nyquist takes real signal off the top of the band, confirmed from the 
   same closed form
   the shipped javascript: aliasOf is Math.abs(f - Math.round(f / fs) * fs)
   every headline number re-derived a second way agrees with the published page
   PASS

== 12. the independent checker refuses every dependent probe
   7 probes that reach the package refused, including one through a helper and one through a name built at runtime
   2 probes accepted, one of which names the package in a comment and in a string, which is what separates this from a grep
   PASS

== 13. privacy scan with planted positive controls and clean negative controls
   scanned 41 tracked files, none of them binary to git, 1 of them empty
   positive controls: 10 planted credentials, every one found
   negative controls: 5 of 5 alarming looking files correctly left alone
   the NUL detector found a planted NUL byte, so its silence above means something
   nothing private, nothing credential shaped, and the scanner is shown to work
   PASS

== 14. sabotage suite, three gates and a null control
   null control: an untouched copy under another name fingerprints 4496f093d7390e0c
   33 of 33 sabotages caught (1 dormant), null control held
   caught by: tests 26, parity 30, independent 4, browser 13
   PASS

== 15. the README is finished and carries this script's own success line
   7 sections, 0 problem(s)
   PASS

== 16. verify did not modify the tree it was verifying
   the tree is byte identical to before this ran
   PASS

VERIFY PASSED: foldback, 16 of 16 steps
```

## Unfinished

**What is covered by tests, and what is not.** The arithmetic is: the fold, the transform, the
filter and the sampler are all in Python with 127 unit tests on them, and the page's JavaScript
copy of the same formulas is compared against that Python value by value. The page's numbers are
checked in a real browser, and so is its layout at four widths, its canvases having drawn
anything at all, and the frequency slider, filter button and order menu changing what it prints.

Not covered:

- **What it sounds like.** Nothing here listens. The samples that reach `destination` are checked
  by rendering the same graph into an `OfflineAudioContext` and transforming the result, which is
  the same code path but not the same as a speaker. Whether the sweep is pleasant, whether the
  volume default is sensible on a given device, and whether the fold is audible as a fold rather
  than as a glitch are all unmeasured.
- **The drawing.** Both canvases are checked for having put more than two thousand coloured
  pixels down, and the numbers they are drawn from are checked, and the axis labels, the dashed
  marker positions and the shaded strip are not. A plot could be drawn upside down and pass.
- **The sweep animation.** The button is not pressed by any check. It drives the same `refresh`
  path that the slider does, which is checked, and the twenty second `requestAnimationFrame` walk
  itself is not.
- **Browsers other than Chrome.** Everything measured here was measured in one headless Chrome on
  one Linux machine. Safari and Firefox report different sample rates and different
  `ScriptProcessorNode` behaviour, and neither has been opened.
- **Sample rates other than 44100 and 48000.** The arithmetic is checked at both, and at 8000,
  96000 and a few others in the fold tests. A device reporting something unusual would still be
  read and used, and the reference block baked into the page only covers the two common rates, so
  the page's self check on such a device compares against nothing for its own rate.
- **The oversampled model above four times the sample rate.** Eight times oversampling means the
  model itself folds above four times fs. The slider stops there, the tests pin where it starts to
  matter, and nothing above it is claimed.
- **Accessibility beyond the basics.** The controls are labelled and the canvases carry
  `role="img"` and an `aria-label`, and no screen reader has been run against the page.

**One assumption worth stating.** The page's corner frequency menu offers 0.80, 0.90 and 0.95
times Nyquist and defaults to 0.90. There is no correct answer there, only a trade between what
the filter takes off the top of the band and what it leaves in the stopband, and the page prints
both sides of that trade rather than picking one and calling it right.

## Licence

MIT. See [LICENSE](LICENSE).
