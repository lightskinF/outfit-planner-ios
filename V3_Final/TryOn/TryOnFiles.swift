import Foundation
import UIKit

/// Where the avatar and the garment layers are kept on the phone.
///
/// Layers are stored per avatar: a new avatar photo gets a new id, and layers
/// made for the old body are simply never looked at again (and are deleted).
nonisolated enum TryOnFiles {
    static var root: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        let url = base.appendingPathComponent("TryOn", isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    static var avatarCutout: URL { root.appendingPathComponent("avatar_cutout.png") }
    static var avatarBase: URL { root.appendingPathComponent("avatar_base.png") }
    static var avatarInfo: URL { root.appendingPathComponent("avatar.json") }
    static var layersRoot: URL { root.appendingPathComponent("layers", isDirectory: true) }

    static func layersDirectory(avatarID: String) -> URL {
        let url = layersRoot.appendingPathComponent(avatarID, isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    static func layer(avatarID: String, itemID: UUID) -> URL {
        layersDirectory(avatarID: avatarID).appendingPathComponent(itemID.uuidString + ".png")
    }

    static func hasLayer(avatarID: String, itemID: UUID) -> Bool {
        FileManager.default.fileExists(atPath: layer(avatarID: avatarID, itemID: itemID).path)
    }

    /// Deletes the layers of every avatar except `avatarID` (all of them if nil).
    static func removeLayers(keeping avatarID: String?) {
        let manager = FileManager.default
        guard let folders = try? manager.contentsOfDirectory(at: layersRoot, includingPropertiesForKeys: nil) else { return }
        for folder in folders where folder.lastPathComponent != avatarID {
            try? manager.removeItem(at: folder)
        }
    }

    /// The photo of a garment as the closet saved it.
    static func garmentImage(fileName: String) -> UIImage? {
        guard !fileName.isEmpty,
              let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else { return nil }
        return UIImage(contentsOfFile: documents.appendingPathComponent(fileName).path)
    }
}

/// What is saved next to the avatar images.
nonisolated struct AvatarInfo: Codable, Sendable {
    var id: String
    var pose: BodyPose?
}
