# Hebrew QA Contractor Instructions

## Quick Links

- QA Reader: [https://sam121.github.io/hebrew-audio-reader/qa.html](https://sam121.github.io/hebrew-audio-reader/qa.html)
- Google Sheet: [https://docs.google.com/spreadsheets/d/1JvDXB7bjEQV_wEO4YTUJJ-S6TXLt8VcqqClz8PetPzs/edit?gid=413834508#gid=413834508](https://docs.google.com/spreadsheets/d/1JvDXB7bjEQV_wEO4YTUJJ-S6TXLt8VcqqClz8PetPzs/edit?gid=413834508#gid=413834508)

## Summary

Use the workflow in two parts:

1. Use the Hebrew QA Reader to place arrows and listen to audio.
2. Use the Google Sheet to record any issues.

Important rule:

- The QA Reader is only for arrow placement and listening.
- The Google Sheet is the only place where issue categories and notes should be recorded.

If a line is fine:

- set the arrow in the QA Reader
- leave `Issue Category` and `Issue Note` blank in the Google Sheet

If a line has a problem:

- set the arrow in the QA Reader
- record the issue in the Google Sheet

## Part 1: How to Use the Hebrew QA Reader

### What the QA Reader is for

Use the QA Reader to:

- go page by page
- select each line
- place the arrow where that line appears on the scanned page
- listen to the line audio
- optionally listen to the whole page audio

Use the QA Reader only for:

- Arrow placement
- Listening

Do not use the QA Reader to record issue categories or notes.

### Step-by-step QA Reader process

For each page:

1. Open the page in the QA Reader.
2. Select a line from the line list.
3. Click on the scanned page where that line appears.
4. This places the arrow for that line.
5. Press `Play line` to listen to that line's audio.
6. Check whether the line sounds correct.
7. Move to the next line and repeat.
8. Press `Save progress` regularly so arrow positions are saved.

### Arrow rules

- If the arrow is wrong, just click again in the correct place.
- You do not need to clear the arrow first.
- `Clear location` is only needed if you want to remove the arrow completely.

### QA Reader status

Each line only has one QA status:

- `Arrow not set`
- `Arrow set`

Meaning:

- `Arrow not set` = the arrow still needs to be placed
- `Arrow set` = the arrow has been placed

### Useful buttons

- `Play line`
  Plays the selected line only.
- `Play whole page`
  Plays the whole page audio.
- `Clear location`
  Removes the arrow entirely.
- `Save progress`
  Saves arrow progress.

## Part 2: How to Use the Google Sheet

### Important rule

The Google Sheet is the only place where you should record problems.

If the line is correct:

- leave `Issue Category` blank
- leave `Issue Note` blank

If the line is wrong:

- choose one `Issue Category`
- fill in `Issue Note` if needed

## Part 3: Issue Categories

Use these exact categories:

- `Google Sheet text error`
- `Hebrew pronunciation error`
- `English pronunciation error`
- `Transliteration pronunciation error`
- `Other`

### What each category means

- `Google Sheet text error`
  The source text in the sheet is wrong.
  Fix the source text directly in the sheet.
  `Issue Note` is optional for this category.

- `Hebrew pronunciation error`
  The printed Hebrew is correct, but the Hebrew audio is spoken incorrectly.

- `English pronunciation error`
  A normal English word, letter, or phrase is spoken incorrectly.

- `Transliteration pronunciation error`
  A Hebrew word written in English letters is spoken incorrectly, for example:
  - `siddur`
  - `Berachah`
  - `Adonai`

- `Other`
  Use only if the issue does not fit the other categories.

## Part 4: How to Write `Issue Note`

### Locked arrow meaning

Whenever you use an arrow note, the meaning is always:

- Left side = wrong now
- Right side = correct target

This rule must always be followed.

### When to use arrow notes

Use arrow notes for:

- `Hebrew pronunciation error`
- `English pronunciation error`
- `Transliteration pronunciation error`
- `Other` when helpful

For these categories, write notes like this:

`wrong now -> should become`

Examples:

- `Berachah -> buh-rah-khah`
- `siddur -> sid-door`
- `B -> bee`
- `בּ -> bet`

### Google Sheet text error notes

For `Google Sheet text error`:

- first fix the text directly in the sheet
- `Issue Note` is optional
- if you write a note, use a short plain explanation, not an arrow example

Good examples:

- `Corrected in sheet`
- `Fixed Hebrew spelling in source text`
- `Corrected vowel in sheet`

Do not use a Hebrew text arrow example here.

### Writing rules

- Be specific.
- Copy the exact wrong word or phrase when using arrow notes.
- Do not write vague comments.

Good:

```text
Berachah -> buh-rah-khah
```

Bad:

```text
sounds wrong
```

### Multiple issues on one line

If there is more than one issue on a line, put one correction per new line.

Use this format:

```text
wrong item -> correct target
wrong item -> correct target
```

Do not use semicolons.
Do not use commas as separators.

## Part 5: Examples by Category

### Google Sheet text error

Use when the source text itself is wrong in the Google Sheet.

Fix the source text in the sheet first.

Optional notes:

```text
Corrected in sheet
```

```text
Fixed Hebrew spelling in source text
```

### Hebrew pronunciation error

Use when the Hebrew text is correct but the spoken result is wrong.

```text
בּ -> bet
```

```text
בָּרוּךְ -> bah-rookh
```

### English pronunciation error

Use when a normal English word or letter is spoken wrongly.

```text
B -> bee
```

```text
the -> thee
```

### Transliteration pronunciation error

Use for Hebrew words written in English letters.

```text
Berachah -> buh-rah-khah
```

```text
siddur -> sid-door
```

```text
Adonai -> ah-doh-nye
```

### Multiple issues on one line

Use one issue per line:

```text
Berachah -> buh-rah-khah
B -> bee
```

Mixed example:

```text
בּ -> bet
siddur -> sid-door
```

## Part 6: What Not to Write

Do not write:

- `sounds wrong`
- `fix this`
- `not natural`
- `Hebrew wrong`
- `bad pronunciation near end`

These are too vague to use reliably.

## Part 7: Full Contractor Workflow

Use this full process for each page:

1. Open the page in the Hebrew QA Reader.
2. Select a line.
3. Click on the scanned page to place the arrow.
4. Press `Play line` and listen carefully.
5. If the line is correct:
   - leave `Issue Category` blank
   - leave `Issue Note` blank
6. If the line has a problem:
   - go to the Google Sheet
   - choose the correct `Issue Category`
7. If the problem is `Google Sheet text error`:
   - correct the source text directly in the sheet
   - `Issue Note` is optional
8. If the problem is a pronunciation-style issue:
   - write the note using `wrong now -> should become`
   - remember: left is wrong, right is good
9. If there is more than one issue on the line:
   - write one correction per new line
10. Repeat for all lines on the page.
11. Press `Save progress` in the QA Reader regularly.
12. Use `Play whole page` if needed to hear the page in context, but still record issues only in the Google Sheet.

## Part 8: Short Version

Use the Hebrew QA Reader only to place arrows and listen to the audio. For each line, click the scanned page to set the arrow, then play the line and check it. If the line is correct, leave Issue Category and Issue Note blank in the Google Sheet. If there is a problem, choose one Issue Category. For pronunciation-style issues, write notes as `wrong now -> should become`. Left is wrong, right is good. If there are multiple issues, put one correction per new line. For Google Sheet text errors, fix the source text directly in the sheet; a note is optional.
