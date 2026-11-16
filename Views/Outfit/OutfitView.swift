import SwiftUI

// MARK: - Dusty Rose Palette
private extension Color {
    static let petal        = Color(hex: "#FDF6F4")
    static let blushLight   = Color(hex: "#F5E8E4")
    static let blush        = Color(hex: "#EDD8D2")
    static let burgundy     = Color(hex: "#A0404A")
    static let rose         = Color(hex: "#C87A80")
    static let deepWine     = Color(hex: "#2A1418")
    static let mauve        = Color(hex: "#8A6060")
    static let blushBorder  = Color(hex: "#E8D4D0")

    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let r, g, b: UInt64
        switch hex.count {
        case 6: (r, g, b) = (int >> 16, (int >> 8) & 0xFF, int & 0xFF)
        default: (r, g, b) = (1, 1, 0)
        }
        self.init(.sRGB, red: Double(r)/255, green: Double(g)/255, blue: Double(b)/255, opacity: 1)
    }
}

// MARK: - UI Support: Shimmer Effect
struct ShimmerView: View {
    @State private var startPoint: UnitPoint = .init(x: -1.8, y: -1.2)
    @State private var endPoint: UnitPoint = .init(x: 0, y: -0.2)

    var body: some View {
        LinearGradient(
            colors: [.clear, .white.opacity(0.3), .clear],
            startPoint: startPoint,
            endPoint: endPoint
        )
        .onAppear {
            withAnimation(.linear(duration: 1.5).repeatForever(autoreverses: false)) {
                startPoint = .init(x: 1, y: 1)
                endPoint = .init(x: 2.2, y: 2.2)
            }
        }
    }
}

// MARK: - OutfitView
//
// The Studio. The avatar is the person's own photo; every garment is fitted on
// it once by the try-on service and kept as a layer (see V3_Final/TryOn).
// Choosing garments here only stacks those layers, so it is instant.
struct OutfitView: View {
    @EnvironmentObject var store: AppStore
    @EnvironmentObject var tryOn: TryOnEngine
    @Binding var selectedTab: Int
    @Binding var previousTab: Int
    @State private var activeCategory: ClothingCategory? = nil
    @State private var showCamera = false
    @State private var showPhotoLibrary = false
    @State private var showSaveOutfit  = false
    @State private var showSavedBanner = false
    @State private var outfitCountBeforeSave = 0

    @State private var displayed: UIImage? = nil        // the stacked layers
    @State private var refined: UIImage? = nil          // the outfit generated in one go, on request
    @State private var snapshot: UIImage? = nil         // what is saved with the outfit
    @State private var isCuttingOut = false
    @State private var isPreparingSnapshot = false
    @State private var notice: String? = nil

    var sortedSelections: [(ClothingCategory, ClothingItem)] {
        store.selectedItems.sorted { $0.key.layerOrder < $1.key.layerOrder }
    }

    private var selectedItems: [ClothingItem] { store.currentOutfitItems }

    /// Changes whenever the picture on the canvas has to be put together again.
    private var compositeKey: String {
        let parts = selectedItems.map { item in
            item.id.uuidString + (tryOn.statuses[item.id] == .ready ? ":1" : ":0")
        }
        return (tryOn.avatar?.id ?? "none") + "|" + parts.joined(separator: ",")
    }

    private var waitingCount: Int {
        tryOn.statuses.values.filter { $0 == .queued || $0 == .generating }.count
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                heroCanvas
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

                selectedItemsStrip
                    .padding(.top, 10)

                categoryPills
                    .padding(.top, 10)

                confirmButton
                    .padding(.horizontal, 20)
                    .padding(.top, 14)
                    .padding(.bottom, 16)
            }
            .background(Color.petal)
            .navigationTitle("Studio")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { toolbarItems }
            .sheet(isPresented: $showCamera) {
                CameraPickerUIKit { image in
                    showCamera = false
                    if let image { useAvatarPhoto(image) }
                }
                .ignoresSafeArea()
            }
            .sheet(isPresented: $showPhotoLibrary) {
                PhotoLibraryPicker { image in
                    showPhotoLibrary = false
                    if let image { useAvatarPhoto(image) }
                }
            }
            .sheet(item: $activeCategory) { cat in
                ItemPickerSheet(category: cat) { item in
                    withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) {
                        if let item {
                            store.selectItem(item)
                        } else {
                            store.removeItem(for: cat)
                        }
                    }
                    activeCategory = nil
                }
                .presentationDetents([.fraction(0.65), .large])
                .presentationDragIndicator(.visible)
            }
            .onChange(of: showSaveOutfit) { _, isShowing in
                if isShowing {
                    outfitCountBeforeSave = store.savedOutfits.count
                }
            }
            .sheet(isPresented: $showSaveOutfit, onDismiss: {
                if store.savedOutfits.count > outfitCountBeforeSave {
                    withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) {
                        showSavedBanner = true
                    }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
                        withAnimation(.easeOut(duration: 0.3)) {
                            showSavedBanner = false
                        }
                    }
                }
            }) {
                SaveOutfitSheet(snapshot: snapshot)
                    .presentationDetents([.fraction(0.38)])
            }
            .overlay(alignment: .top) {
                if showSavedBanner {
                    HStack(spacing: 10) {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.system(size: 18))
                            .foregroundColor(.white)
                        Text("Saved successfully in My Collection")
                            .font(.system(size: 14, weight: .semibold))
                            .foregroundColor(.white)
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 12)
                    .background(
                        Capsule()
                            .fill(
                                LinearGradient(colors: [.burgundy, .rose],
                                               startPoint: .leading, endPoint: .trailing)
                            )
                            .shadow(color: Color.burgundy.opacity(0.3), radius: 10, y: 4)
                    )
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .padding(.top, 8)
                }
            }
            .task {
                // An avatar saved by an earlier version of the app becomes a studio avatar.
                if tryOn.avatar == nil, let old = store.avatarImage {
                    try? await tryOn.setAvatar(cutout: old, requirePose: false)
                }
                tryOn.sync(items: store.wardrobeItems)
            }
        }
    }

    // MARK: - Canvas

    var heroCanvas: some View {
        ZStack {
            // The same flat colour as the backdrop of the avatar, so the picture has no visible border.
            RoundedRectangle(cornerRadius: 28)
                .fill(Color.blushLight)

            if isCuttingOut || tryOn.isPreparingAvatar {
                busyCard("Preparing your avatar…")
            } else if let avatar = tryOn.avatar {
                Image(uiImage: refined ?? displayed ?? avatar.base)
                    .resizable()
                    .scaledToFit()
                    .clipShape(RoundedRectangle(cornerRadius: 22))
                    .padding(8)
                    .interactive3DEffect()
                    .transition(.opacity)
                    .overlay(alignment: .topTrailing) { perfectFitButton.padding(16) }
                    .overlay(alignment: .bottom) { statusArea.padding(14) }
            } else {
                addPhotoPrompt
            }
        }
        .padding(.horizontal, 16)
        .animation(.easeInOut(duration: 0.25), value: compositeKey)
        .task(id: compositeKey) {
            refined = tryOn.cachedRender(items: selectedItems)
            displayed = await tryOn.composite(items: selectedItems)
        }
    }

    private func busyCard(_ text: String) -> some View {
        VStack(spacing: 14) {
            ProgressView()
                .scaleEffect(1.3)
                .tint(.burgundy)
            Text(text)
                .font(.system(size: 14, weight: .medium, design: .rounded))
                .foregroundColor(.rose)
        }
    }

    private var addPhotoPrompt: some View {
        VStack(spacing: 14) {
            Image(systemName: "person.crop.rectangle.badge.plus")
                .font(.system(size: 44, weight: .light))
                .foregroundStyle(
                    LinearGradient(colors: [.rose.opacity(0.6), .burgundy.opacity(0.5)],
                                   startPoint: .topLeading, endPoint: .bottomTrailing)
                )
            Text("Add a full-body photo of yourself")
                .font(.system(size: 15, weight: .semibold))
                .foregroundColor(.deepWine)
            Text("Stand straight in front of a plain wall, whole body in the frame, arms slightly away from your body. Fitted clothes work best.")
                .font(.system(size: 13))
                .foregroundColor(.mauve)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 28)
            if let notice {
                Text(notice)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundColor(.burgundy)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 28)
            }
            Menu {
                Button { showCamera = true } label: {
                    Label("Take Photo", systemImage: "camera")
                }
                Button { showPhotoLibrary = true } label: {
                    Label("Choose from Library", systemImage: "photo.on.rectangle")
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "camera.fill")
                    Text("Add My Photo")
                        .font(.system(size: 15, weight: .semibold))
                }
                .foregroundColor(.white)
                .padding(.horizontal, 24)
                .padding(.vertical, 12)
                .background(
                    Capsule().fill(
                        LinearGradient(colors: [.burgundy, .rose],
                                       startPoint: .leading, endPoint: .trailing)
                    )
                )
            }
        }
    }

    // MARK: - Status of the garments on the avatar

    @ViewBuilder
    private var statusArea: some View {
        VStack(spacing: 6) {
            if !tryOn.isConfigured {
                chip("The try-on service is not set up yet", icon: "wrench.and.screwdriver")
            } else if !tryOn.hasConsent {
                consentCard
            } else {
                ForEach(selectedItems) { item in
                    statusChip(for: item)
                }
                if let reason = tryOn.pauseReason, waitingCount > 0 {
                    Button { tryOn.resume() } label: {
                        chip(reason, icon: "pause.circle")
                    }
                    .buttonStyle(.plain)
                }
            }
            if let notice {
                chip(notice, icon: "exclamationmark.triangle")
            }
        }
    }

    @ViewBuilder
    private func statusChip(for item: ClothingItem) -> some View {
        switch tryOn.statuses[item.id] {
        case .some(.queued), .some(.generating):
            HStack(spacing: 8) {
                ProgressView().controlSize(.small).tint(.burgundy)
                Text("Fitting \(item.name) on you…")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(.deepWine)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(.ultraThinMaterial, in: Capsule())
        case .some(.failed(let message)):
            Button { tryOn.retry(item) } label: {
                chip("\(item.name): \(message)", icon: "arrow.clockwise")
            }
            .buttonStyle(.plain)
        case .some(.unsupported):
            chip("\(item.category.rawValue) can't be tried on yet", icon: "info.circle")
        case .some(.ready), .none:
            EmptyView()
        }
    }

    private func chip(_ text: String, icon: String) -> some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 12, weight: .semibold))
                .foregroundColor(.burgundy)
            Text(text)
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(.deepWine)
                .multilineTextAlignment(.leading)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 14))
    }

    private var consentCard: some View {
        VStack(spacing: 10) {
            Text("See your clothes on you")
                .font(.system(size: 15, weight: .bold))
                .foregroundColor(.deepWine)
            Text("To dress your avatar, your avatar photo and the photos of your clothes are sent to the try-on service, which creates the images. Each garment is sent once.")
                .font(.system(size: 12))
                .foregroundColor(.mauve)
                .multilineTextAlignment(.center)
            Button { tryOn.hasConsent = true } label: {
                Text("Allow and continue")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(.white)
                    .padding(.horizontal, 22)
                    .padding(.vertical, 10)
                    .background(
                        Capsule().fill(
                            LinearGradient(colors: [.burgundy, .rose],
                                           startPoint: .leading, endPoint: .trailing)
                        )
                    )
            }
        }
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 20))
    }

    /// Generates the whole outfit in one go, for hems and waistbands that meet naturally.
    @ViewBuilder
    private var perfectFitButton: some View {
        let cost = tryOn.renderCost(items: selectedItems)
        if tryOn.isConfigured, tryOn.hasConsent, cost > 0, refined == nil {
            Button {
                Task { await perfectFit() }
            } label: {
                HStack(spacing: 6) {
                    if tryOn.isRendering {
                        ProgressView().controlSize(.small).tint(.white)
                    } else {
                        Image(systemName: "sparkles")
                    }
                    Text(tryOn.isRendering ? "Refining…" : "Perfect fit")
                        .font(.system(size: 12, weight: .semibold))
                }
                .foregroundColor(.white)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    Capsule().fill(
                        LinearGradient(colors: [.burgundy, .rose],
                                       startPoint: .leading, endPoint: .trailing)
                    )
                )
            }
            .disabled(tryOn.isRendering)
        }
    }

    private func perfectFit() async {
        notice = nil
        let items = selectedItems
        let key = compositeKey
        do {
            let image = try await tryOn.render(items: items)
            if key == compositeKey { refined = image }       // the selection may have changed meanwhile
        } catch {
            notice = error.localizedDescription
        }
    }

    // MARK: - Avatar photo

    private func useAvatarPhoto(_ image: UIImage) {
        notice = nil
        isCuttingOut = true
        Task {
            let cutout = await ImagePreProcessor.removePersonBackground(image)
            isCuttingOut = false
            do {
                try await tryOn.setAvatar(cutout: cutout)
                store.saveAvatar(cutout)
            } catch {
                notice = error.localizedDescription
            }
        }
    }

    private func removeAvatar() {
        store.deleteAvatar()
        tryOn.removeAvatar()
        displayed = nil
        refined = nil
    }

    private func saveTapped() {
        isPreparingSnapshot = true
        Task {
            // Saved outfits are shown as cut-outs everywhere else in the app.
            if let picture = refined ?? displayed {
                snapshot = await ImagePreProcessor.removePersonBackground(picture)
            } else {
                snapshot = nil
            }
            isPreparingSnapshot = false
            showSaveOutfit = true
        }
    }

    var selectedItemsStrip: some View {
        Group {
            if sortedSelections.isEmpty {
                Text("Tap a category below to start building")
                    .font(.system(size: 13))
                    .foregroundColor(.mauve)
                    .frame(height: 56)
                    .frame(maxWidth: .infinity)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) {
                        ForEach(sortedSelections, id: \.1.id) { (cat, item) in
                            Button { withAnimation { store.removeItem(for: cat) } } label: {
                                HStack(spacing: 8) {
                                    if let img = store.loadImage(for: item) {
                                        Image(uiImage: img)
                                            .resizable()
                                            .scaledToFill()
                                            .frame(width: 36, height: 36)
                                            .clipShape(RoundedRectangle(cornerRadius: 8))
                                    }
                                    VStack(alignment: .leading, spacing: 1) {
                                        Text(item.name)
                                            .font(.system(size: 12, weight: .semibold))
                                            .foregroundColor(.deepWine)
                                        Text(cat.rawValue)
                                            .font(.system(size: 10))
                                            .foregroundColor(.mauve)
                                    }
                                    Image(systemName: "xmark")
                                        .font(.system(size: 10, weight: .bold))
                                        .foregroundColor(.mauve)
                                }
                                .padding(8)
                                .background(
                                    RoundedRectangle(cornerRadius: 14)
                                        .fill(Color.blushLight)
                                        .overlay(
                                            RoundedRectangle(cornerRadius: 14)
                                                .stroke(Color.blushBorder, lineWidth: 1)
                                        )
                                )
                            }.buttonStyle(.plain)
                        }
                    }.padding(.horizontal, 16)
                }.frame(height: 56)
            }
        }
    }

    var categoryPills: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(ClothingCategory.allCases) { cat in
                    CategoryPill(category: cat, hasSelection: store.selectedItems[cat] != nil) { activeCategory = cat }
                }
            }.padding(.horizontal, 16)
        }
    }

    var confirmButton: some View {
        Button(action: saveTapped) {
            HStack {
                if isPreparingSnapshot {
                    ProgressView().tint(.white)
                } else {
                    Image(systemName: "checkmark.circle.fill")
                }
                Text("Save Outfit").font(.system(size: 17, weight: .bold))
            }
            .foregroundColor(.white)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 16)
            .background(
                RoundedRectangle(cornerRadius: 16)
                    .fill(
                        store.selectedItems.isEmpty
                            ? AnyShapeStyle(Color.blush)
                            : AnyShapeStyle(LinearGradient(colors: [.burgundy, .rose], startPoint: .leading, endPoint: .trailing))
                    )
            )
        }.disabled(store.selectedItems.isEmpty || isPreparingSnapshot)
    }

    @ToolbarContentBuilder
    var toolbarItems: some ToolbarContent {
        ToolbarItem(placement: .navigationBarLeading) {
            Button {
                withAnimation { selectedTab = previousTab }
            } label: {
                Image(systemName: "chevron.left")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(Color.burgundy)
            }
        }
        ToolbarItem(placement: .navigationBarTrailing) {
            HStack(spacing: 14) {
                if !store.selectedItems.isEmpty {
                    Button("Clear") { withAnimation { store.clearAllSelections() } }
                        .foregroundColor(.mauve)
                }
                Menu {
                    Button { showCamera = true } label: {
                        Label("Take Photo", systemImage: "camera")
                    }
                    Button { showPhotoLibrary = true } label: {
                        Label("Choose from Library", systemImage: "photo.on.rectangle")
                    }
                    if tryOn.avatar != nil || store.avatarImage != nil {
                        Divider()
                        Button(role: .destructive) {
                            withAnimation { removeAvatar() }
                        } label: {
                            Label("Remove Avatar", systemImage: "trash")
                        }
                    }
                } label: {
                    Image(systemName: "person.circle")
                        .font(.system(size: 20))
                        .foregroundStyle(Color.burgundy)
                }
            }
        }
    }
}

// MARK: - CategoryPill
struct CategoryPill: View {
    let category: ClothingCategory
    let hasSelection: Bool
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: 6) {
                Text(category.emoji)
                Text(category.rawValue)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundColor(hasSelection ? .burgundy : .deepWine)
                if hasSelection {
                    Circle()
                        .fill(Color.burgundy)
                        .frame(width: 7, height: 7)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 20)
                    .fill(hasSelection ? Color.burgundy.opacity(0.1) : Color.blushLight)
                    .overlay(
                        RoundedRectangle(cornerRadius: 20)
                            .stroke(hasSelection ? Color.burgundy.opacity(0.3) : Color.blushBorder, lineWidth: 1)
                    )
            )
        }.buttonStyle(.plain)
    }
}

// MARK: - ItemPickerSheet
struct ItemPickerSheet: View {
    @EnvironmentObject var store: AppStore
    let category: ClothingCategory
    let onSelect: (ClothingItem?) -> Void

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 16) {
                    ForEach(store.items(for: category)) { item in
                        Button(action: { onSelect(item) }) {
                            VStack {
                                if let img = store.loadImage(for: item) {
                                    Image(uiImage: img)
                                        .resizable()
                                        .scaledToFit()
                                        .frame(height: 100)
                                }
                                Text(item.name)
                                    .font(.caption)
                                    .foregroundColor(.deepWine)
                            }
                            .padding(8)
                            .background(Color.blushLight, in: RoundedRectangle(cornerRadius: 12))
                            .overlay(
                                RoundedRectangle(cornerRadius: 12)
                                    .stroke(Color.blushBorder, lineWidth: 1)
                            )
                        }
                    }
                }.padding()
            }
            .background(Color.petal)
            .navigationTitle(category.rawValue)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") { onSelect(nil) }
                        .foregroundColor(.burgundy)
                }
            }
        }
    }
}

// MARK: - SaveOutfitSheet
struct SaveOutfitSheet: View {
    @EnvironmentObject var store: AppStore
    @Environment(\.dismiss) var dismiss
    @State private var name = ""
    let snapshot: UIImage?

    var body: some View {
        VStack(spacing: 16) {
            Capsule()
                .fill(Color.blushBorder)
                .frame(width: 36, height: 5)
                .padding(.top, 8)
            Text("Save Outfit")
                .font(.headline)
                .foregroundColor(.deepWine)
            TextField("Outfit Name", text: $name)
                .textFieldStyle(.roundedBorder)
                .foregroundColor(.deepWine)
                .padding(.horizontal)
            Button("Save") {
                store.saveCurrentOutfit(name: name, snapshot: snapshot)
                dismiss()
            }
            .buttonStyle(.borderedProminent)
            .tint(.burgundy)
            .padding(.bottom, 8)
        }
        .background(Color.petal)
        .presentationSizing(.fitted)
    }
}
