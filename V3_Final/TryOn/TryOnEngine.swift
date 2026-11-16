import SwiftUI
import UIKit
import Combine

/// Keeps every garment of the closet ready to be worn by the avatar.
///
/// Each garment is sent to the try-on service once. What comes back is a
/// transparent layer, saved on the phone. Dressing the avatar afterwards is
/// just stacking layers: instant, offline, and free.
final class TryOnEngine: ObservableObject {

    struct Avatar: Equatable {
        let id: String
        let pose: BodyPose?
        let base: UIImage

        static func == (lhs: Avatar, rhs: Avatar) -> Bool { lhs.id == rhs.id }
    }

    private struct Job {
        let itemID: UUID
        let category: String
        let imageFileName: String
    }

    @Published private(set) var avatar: Avatar?
    @Published private(set) var statuses: [UUID: LayerStatus] = [:]
    @Published private(set) var isPreparingAvatar = false
    @Published private(set) var isRendering = false
    /// Why the queue is waiting, if it is (shown in the Studio).
    @Published private(set) var pauseReason: String?
    /// The person agreed to send their photos to the try-on service.
    @Published var hasConsent: Bool {
        didSet {
            UserDefaults.standard.set(hasConsent, forKey: "tryOnConsent")
            if hasConsent { resume() }
        }
    }

    private let client = TryOnClient()
    private var queue: [Job] = []
    private var worker: Task<Void, Never>?
    private var supported: Set<String> = ["top", "bottom", "outerwear"]
    private var askedServerForCategories = false
    private var lastItems: [ClothingItem] = []
    private var composites: [String: UIImage] = [:]
    private var renders: [String: UIImage] = [:]

    var isConfigured: Bool { TryOnConfig.current.serverURL != nil }

    init() {
        hasConsent = UserDefaults.standard.bool(forKey: "tryOnConsent")
        loadAvatar()
    }

    // MARK: - Avatar

    private func loadAvatar() {
        guard let data = try? Data(contentsOf: TryOnFiles.avatarInfo),
              let info = try? JSONDecoder().decode(AvatarInfo.self, from: data),
              let base = UIImage(contentsOfFile: TryOnFiles.avatarBase.path),
              FileManager.default.fileExists(atPath: TryOnFiles.avatarCutout.path) else { return }
        avatar = Avatar(id: info.id, pose: info.pose, base: base)
    }

    /// Makes `cutout` (a person on a transparent background) the avatar.
    /// Every garment is then fitted again, because the body changed.
    func setAvatar(cutout: UIImage, requirePose: Bool = true) async throws {
        isPreparingAvatar = true
        defer { isPreparingAvatar = false }

        let result = try await Task.detached(priority: .userInitiated) {
            try AvatarBuilder.build(from: cutout, requirePose: requirePose)
        }.value
        guard let cutoutPNG = result.cutout.pngData(), let basePNG = result.base.pngData() else {
            throw AvatarProblem.noPerson
        }
        let info = AvatarInfo(id: UUID().uuidString, pose: result.pose)
        try cutoutPNG.write(to: TryOnFiles.avatarCutout, options: .atomic)
        try basePNG.write(to: TryOnFiles.avatarBase, options: .atomic)
        try JSONEncoder().encode(info).write(to: TryOnFiles.avatarInfo, options: .atomic)

        worker?.cancel()
        worker = nil
        queue.removeAll()
        statuses.removeAll()
        composites.removeAll()
        renders.removeAll()
        TryOnFiles.removeLayers(keeping: info.id)
        avatar = Avatar(id: info.id, pose: info.pose, base: result.base)
        sync(items: lastItems)
    }

    func removeAvatar() {
        worker?.cancel()
        worker = nil
        queue.removeAll()
        statuses.removeAll()
        composites.removeAll()
        renders.removeAll()
        avatar = nil
        for url in [TryOnFiles.avatarCutout, TryOnFiles.avatarBase, TryOnFiles.avatarInfo] {
            try? FileManager.default.removeItem(at: url)
        }
        TryOnFiles.removeLayers(keeping: nil)
    }

    /// A short hint if `cutout` would not make a good avatar, nil if it is fine.
    func avatarHint(for cutout: UIImage) async -> String? {
        do {
            _ = try await Task.detached(priority: .userInitiated) {
                try AvatarBuilder.build(from: cutout, requirePose: true)
            }.value
            return nil
        } catch {
            return (error as? AvatarProblem)?.errorDescription
                ?? "We couldn't check this photo. A full-body photo, standing straight, works best."
        }
    }

    // MARK: - Closet

    /// Call whenever the closet changes: new garments are queued, deleted ones forgotten.
    func sync(items: [ClothingItem]) {
        lastItems = items
        guard let avatar else { return }

        let ids = Set(items.map(\.id))
        for id in statuses.keys where !ids.contains(id) {
            statuses[id] = nil
            try? FileManager.default.removeItem(at: TryOnFiles.layer(avatarID: avatar.id, itemID: id))
        }
        queue.removeAll { !ids.contains($0.itemID) }

        for item in items {
            if TryOnFiles.hasLayer(avatarID: avatar.id, itemID: item.id) {
                statuses[item.id] = .ready
                continue
            }
            if !supported.contains(item.category.tryOnName) {
                statuses[item.id] = .unsupported
                continue
            }
            switch statuses[item.id] {
            case .queued, .generating, .failed:
                continue
            default:
                enqueue(item)
            }
        }
        resume()
    }

    func retry(_ item: ClothingItem) {
        guard avatar != nil, statuses[item.id] != .generating, statuses[item.id] != .ready else { return }
        queue.removeAll { $0.itemID == item.id }
        pauseReason = nil
        enqueue(item, first: true)
        resume()
    }

    private func enqueue(_ item: ClothingItem, first: Bool = false) {
        guard !item.imageFileName.isEmpty else {
            statuses[item.id] = .failed("This item has no photo.")
            return
        }
        let job = Job(itemID: item.id, category: item.category.tryOnName, imageFileName: item.imageFileName)
        if first { queue.insert(job, at: 0) } else { queue.append(job) }
        statuses[item.id] = .queued
    }

    /// Starts working through the queue, if everything needed is in place.
    func resume() {
        guard worker == nil, hasConsent, isConfigured, avatar != nil, !queue.isEmpty else { return }
        pauseReason = nil
        worker = Task {
            await refreshSupportedCategories()
            while !Task.isCancelled, !queue.isEmpty {
                let job = queue.removeFirst()
                let keepGoing = await run(job)
                if !keepGoing { break }
            }
            worker = nil
        }
    }

    private func refreshSupportedCategories() async {
        guard !askedServerForCategories else { return }
        guard let categories = try? await client.supportedCategories(), !categories.isEmpty else { return }
        askedServerForCategories = true
        supported = Set(categories)
        // Garments judged with the default list may now be possible, or not.
        for item in lastItems where statuses[item.id] == .unsupported && supported.contains(item.category.tryOnName) {
            enqueue(item)
        }
        for job in queue where !supported.contains(job.category) {
            statuses[job.itemID] = .unsupported
        }
        queue.removeAll { !supported.contains($0.category) }
    }

    /// Fits one garment. Returns false when the queue should stop for now.
    private func run(_ job: Job) async -> Bool {
        guard let avatar else { return false }
        statuses[job.itemID] = .generating
        do {
            let fileName = job.imageFileName
            let uploads = await Task.detached(priority: .utility) { () -> (avatar: Data, garment: Data)? in
                guard let avatarPNG = try? Data(contentsOf: TryOnFiles.avatarCutout),
                      let photo = TryOnFiles.garmentImage(fileName: fileName),
                      let garmentPNG = OutfitCompositor.uploadData(for: photo) else { return nil }
                return (avatarPNG, garmentPNG)
            }.value
            guard let uploads else {
                statuses[job.itemID] = .failed("This item's photo could not be read.")
                return true
            }
            let layer = try await client.layer(avatarPNG: uploads.avatar, garmentPNG: uploads.garment,
                                               category: job.category, pose: avatar.pose)
            // The avatar may have been replaced while the garment was being fitted.
            guard self.avatar?.id == avatar.id else { return false }
            try layer.write(to: TryOnFiles.layer(avatarID: avatar.id, itemID: job.itemID), options: .atomic)
            statuses[job.itemID] = .ready
            composites.removeAll()
            return true
        } catch let failure as TryOnFailure {
            if failure.stopsQueue {
                // Not this garment's fault: put it back and wait.
                statuses[job.itemID] = .queued
                queue.insert(job, at: 0)
                pauseReason = failure.userMessage
                return false
            }
            if failure.code == "category_not_supported" {
                statuses[job.itemID] = .unsupported
            } else {
                statuses[job.itemID] = .failed(failure.userMessage)
            }
            return true
        } catch {
            statuses[job.itemID] = .failed("The layer could not be saved on this device.")
            return true
        }
    }

    // MARK: - Dressing the avatar

    /// The garments of `items` that are ready, innermost first.
    private func readyItems(_ items: [ClothingItem]) -> [ClothingItem] {
        items.filter { statuses[$0.id] == .ready }
            .sorted { $0.category.layerOrder < $1.category.layerOrder }
    }

    private func key(_ items: [ClothingItem]) -> String {
        (avatar?.id ?? "") + "|" + items.map(\.id.uuidString).joined(separator: ",")
    }

    /// The avatar wearing `items`, made by stacking the saved layers. No network.
    func composite(items: [ClothingItem]) async -> UIImage? {
        guard let avatar else { return nil }
        let ready = readyItems(items)
        if ready.isEmpty { return avatar.base }
        let cacheKey = key(ready)
        if let cached = composites[cacheKey] { return cached }

        let layers = ready.map { TryOnFiles.layer(avatarID: avatar.id, itemID: $0.id) }
        let image = await Task.detached(priority: .userInitiated) {
            OutfitCompositor.compose(base: TryOnFiles.avatarBase, layers: layers)
        }.value
        if let image {
            if composites.count > 24 { composites.removeAll() }
            composites[cacheKey] = image
        }
        return image
    }

    /// How many generations `render` would use for these items.
    func renderCost(items: [ClothingItem]) -> Int { readyItems(items).count }

    func cachedRender(items: [ClothingItem]) -> UIImage? { renders[key(readyItems(items))] }

    /// The whole outfit generated in one go, garment after garment, for a
    /// result where hems and waistbands meet naturally. Uses one generation
    /// per garment, so it is done on request, not while browsing.
    func render(items: [ClothingItem]) async throws -> UIImage {
        guard let avatar else { throw TryOnFailure.notConfigured }
        let ready = readyItems(items)
        let cacheKey = key(ready)
        if let cached = renders[cacheKey] { return cached }

        isRendering = true
        defer { isRendering = false }

        let sources = ready.map { (category: $0.category.tryOnName, fileName: $0.imageFileName) }
        let uploads = await Task.detached(priority: .userInitiated) { () -> (avatar: Data, garments: [TryOnClient.Garment])? in
            guard let avatarPNG = try? Data(contentsOf: TryOnFiles.avatarCutout) else { return nil }
            var garments: [TryOnClient.Garment] = []
            for source in sources {
                guard let photo = TryOnFiles.garmentImage(fileName: source.fileName),
                      let png = OutfitCompositor.uploadData(for: photo) else { return nil }
                garments.append(TryOnClient.Garment(category: source.category, png: png))
            }
            return (avatarPNG, garments)
        }.value
        guard let uploads, !uploads.garments.isEmpty else {
            throw TryOnFailure(code: "bad_image", message: "The photos could not be read.")
        }
        let data = try await client.render(avatarPNG: uploads.avatar, garments: uploads.garments, pose: avatar.pose)
        guard let image = UIImage(data: data) else {
            throw TryOnFailure(code: "bad_response", message: "The image could not be decoded.")
        }
        if renders.count > 12 { renders.removeAll() }
        renders[cacheKey] = image
        return image
    }
}
