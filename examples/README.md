# Alice's Adventures in Wonderland

Load `example.epub`, `example.m4b` and `example.sync-v2.json` together.

The example contains the opening of Chapter 1, “Down the Rabbit-Hole,” from Lewis Carroll's *Alice's Adventures in Wonderland*. The audio is a 22-second excerpt of the public-domain recording, from 00:00:22 to 00:00:44 in the source M4B. The EPUB was created for this excerpt from the public-domain text. The sidecar uses timestamps relative to the start of the clip. The final timing ends at the clip boundary.

Run `python generate.py` to rebuild the excerpt EPUB and sidecar using the bundled M4B. To regenerate the M4B too, install FFmpeg and pass `--source-audio` with the original, matching recording.
