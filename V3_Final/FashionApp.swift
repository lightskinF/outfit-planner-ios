import SwiftUI

@main
struct FashionApp: App {
    // We remove 'private' here to ensure the state is managed
    // correctly at the top level of the app.
    @StateObject var store = AppStore()
    // Fits the garments on the avatar and keeps the resulting layers.
    @StateObject var tryOn = TryOnEngine()

    var body: some Scene {
        WindowGroup {
            ContentView()
                // This 'injects' your AppStore into every view in the app
                // so Onboarding, Outfit, and Closet all share the same data.
                .environmentObject(store)
                .environmentObject(tryOn)
        }
    }
}
