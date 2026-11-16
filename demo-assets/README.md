# Demo images

These are the images of the first prototype: photos of three garments and
pictures of an avatar wearing them, generated one by one with an image model.
The app used to pick one of these pictures instead of trying anything on.

The app no longer uses them (they added about 200 MB to it). They are kept
because the server tests use them to check that stacking single-garment layers
gives the same outfit as a picture generated in one go
(`backend/tests/test_demo_assets.py`).
