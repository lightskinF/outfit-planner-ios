# Virtual wardrobe and outfit planner (iOS prototype)

An iOS app where you photograph your clothes, try them on a virtual avatar, save the outfits you like and schedule them on a calendar. I built it during a one-month Foundation Program (Apple Developer Academy, Università degli studi di Napoli Federico II), in Swift and SwiftUI.

The concept is mine and I led the project, from the first idea to the final presentation, which I gave in English.

Demo video: [https://youtube.com/shorts/cQxEbVqXol0]


## Why I wanted to build this

Every morning I lose time deciding what to wear, and half the wardrobe ends up on the bed. When I looked into it I found I was not alone: the research I read describes the morning outfit choice as a recurring source of stress, at the time of day when cortisol is already at its peak. [[add 1-2 references]]

So the idea is simple. Decide the evening before, or days ahead, when you are calm. Keep your wardrobe on your phone, see the clothes on an avatar of yourself without pulling anything out of the closet, and assign each outfit to a day or an occasion: the office, school, a dinner.

## My role

- I came up with the concept and did the research behind it.
- I led the project for the whole program: what to build, in which order, and what to simulate for the demo.
- I took the main responsibility for the final pitch and demo, in English. It went well.
- I worked on the Swift code. 

## What works today

- Onboarding with your name, location permission and a full-body photo that becomes your avatar. The background is removed on the phone.
- Closet: take or pick a photo of a garment, the background is removed automatically, and the item is stored by category (top, bottom, outerwear, shoes, accessories). You can search and delete.
- Studio: pick items from the closet, see them on the avatar, name the outfit and save it.
- Planner: a calendar, written from scratch, where you assign a saved outfit to a date. It works fully inside the app and the plan is kept between launches.
- Home: greeting, current weather where you are, and the outfit planned for today.

## What is simulated in the demo

This is a prototype and one month is not enough for a real virtual try-on, so the Studio uses a shortcut. It does not drape the garment on the body. It picks one of 27 pre-rendered images of the avatar (3 shirts x 3 trousers x 3 pairs of shoes) by matching the name and brand of the items you select. The avatar and the clothes in the demo are therefore hard-coded.

A realistic try-on is the difficult part of this idea: the way fabric falls on a body, the measurements of the person, and a result good-looking enough that you actually want to use it. That needs more time, data and computing power than we had.

## How it is built

There is a single `AppStore` object, created at launch and passed to every view through the SwiftUI environment. All data goes through it.

Storage is split in two. Items, outfits and calendar entries are `Codable` structs saved as JSON in `UserDefaults` and written again on every change. Images are PNG files in the app's Documents folder, and each model only keeps the file name. This keeps `UserDefaults` small.

Background removal uses Apple's Vision framework and runs on the device: `VNGeneratePersonSegmentationRequest` for the avatar and `VNGenerateForegroundInstanceMaskRequest` for clothes (this one requires iOS 17). Images are scaled down to 2048 px before processing, the mask is applied with Core Image, and the work is done off the main thread with async/await. No photo ever leaves the phone.

The calendar is built on a `LazyVGrid` rather than on the system component. The outfit cards have a 3D tilt effect that follows your finger, built as a custom `ViewModifier`.

Weather comes from Open-Meteo, which is free and needs no API key. The position comes from CoreLocation.

There are no third-party libraries and no backend. Frameworks used: SwiftUI, UIKit, Vision, Core Image, CoreLocation, PhotosUI, Foundation.

```
FashionApp
  AppStore
    wardrobe, outfits, calendar   -> UserDefaults (JSON)
    images                        -> Documents/*.png
    current selection in Studio   -> memory only
```

## The idea was not far off

Shortly after we finished the prototype, on 16 March 2026, CATCHES and NVIDIA announced RealFit: a digital twin made from your photo and measurements, with physics-based fabric simulation and generative AI. AMIRI put it live on its website the same day ([press release](https://www.businesswire.com/news/home/20260316837622/en/CATCHES-Launches-Generative-AI-with-Physics-Based-Sizing-Technology-for-Fashion-E-Commerce-with-AMIRI-Powered-by-NVIDIA)).

Zara was already doing something similar in some countries: in its app you upload a selfie and a full-body photo and get an avatar wearing the clothes you are looking at ([article](https://mexicobusiness.news/ecommerce/news/zara-deploys-generative-ai-models-virtual-fitting-rooms)).

Those are fitting rooms for clothes you might buy. Mine is for the clothes you already own, with the planning on top.

## What I would like to do next

Those systems get their realism from heavy models running on GPUs in a data centre. Every try-on costs energy, and water to cool the servers.

My proposal for the next step of this project is to look for a way to get a realistic try-on while using as few resources as possible. Some starting points: keep as much of the computation as possible on the phone, as the prototype already does for segmentation; and avoid recomputing, since a wardrobe changes slowly and a garment fitted to your avatar once does not need to be generated again every morning.

After that come the simpler things: linking the planner to the iPhone calendar, so outfits can be tied to your real events, suggesting outfits based on the weather, and sync between devices.

This needs time and resources that I do not have alone. I am looking for people who want to work on it with me. If you are interested, write to me: [[email / LinkedIn]]

## Running it

You need a Mac with Xcode and iOS 17 or later.

```
git clone https://github.com/[[username]]/[[repo]].git
open [[ProjectName]].xcodeproj
```

Run on a simulator or a device. The camera only works on a real device; in the simulator you can pick photos from the library. No keys or configuration needed.

## Author

Fabio Greco. Concept, project lead and presenter. Developed in a small team during the program.

## Licence

Copyright (c) 2026. All rights reserved.

The source code is published for portfolio and evaluation purposes only. The product concept is by Fabio Greco; if you want to build on it, contact me.
