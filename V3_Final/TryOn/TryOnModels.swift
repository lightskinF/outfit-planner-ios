import Foundation
import CoreGraphics

// Everything about the "studio": the fixed frame every avatar and every
// garment layer lives in. The server works in the same frame, so a layer it
// returns can be drawn over the avatar without any alignment.

nonisolated enum TryOnStudio {
    /// 2:3 portrait, the shape try-on models work at.
    static let canvasSize = CGSize(width: 1024, height: 1536)
    /// The flat backdrop behind the avatar (the app's "blush light").
    static let backgroundHex = "#F5E8E4"
    static let backgroundRGB: (red: CGFloat, green: CGFloat, blue: CGFloat) = (245.0 / 255.0, 232.0 / 255.0, 228.0 / 255.0)
}

/// Body joints as fractions of the studio frame (x to the right, y downwards).
nonisolated struct BodyPose: Codable, Equatable, Sendable {
    static let requiredJoints = [
        "nose", "left_shoulder", "right_shoulder", "left_hip", "right_hip",
        "left_knee", "right_knee", "left_ankle", "right_ankle",
    ]

    var joints: [String: [Double]]

    private func y(_ names: [String]) -> Double? {
        var sum = 0.0
        for name in names {
            guard let point = joints[name], point.count == 2 else { return nil }
            sum += point[1]
        }
        return sum / Double(names.count)
    }

    var isComplete: Bool {
        BodyPose.requiredJoints.allSatisfy { joints[$0]?.count == 2 }
    }

    /// Head above shoulders above hips above knees above ankles.
    var isUpright: Bool {
        guard let nose = y(["nose"]),
              let shoulders = y(["left_shoulder", "right_shoulder"]),
              let hips = y(["left_hip", "right_hip"]),
              let knees = y(["left_knee", "right_knee"]),
              let ankles = y(["left_ankle", "right_ankle"]) else { return false }
        return nose < shoulders && shoulders < hips && hips < knees && knees < ankles
    }

    var jsonString: String? {
        guard let data = try? JSONSerialization.data(withJSONObject: joints, options: [.sortedKeys]) else { return nil }
        return String(data: data, encoding: .utf8)
    }
}

/// Where a garment stands on its way to the avatar.
nonisolated enum LayerStatus: Equatable, Sendable {
    case queued
    case generating
    case ready
    case failed(String)
    case unsupported
}

nonisolated enum AvatarProblem: LocalizedError, Equatable {
    case noPerson
    case tooSmall
    case bodyNotVisible
    case notUpright

    var errorDescription: String? {
        switch self {
        case .noPerson:
            return "We couldn't find a person in this photo. Try one where you stand in front of a plain wall."
        case .tooSmall:
            return "You are too far away in this photo. Step closer, keeping your whole body in the frame."
        case .bodyNotVisible:
            return "We need your whole body, from head to feet. Step back until your feet are in the frame."
        case .notUpright:
            return "Stand straight, facing the camera, with your arms slightly away from your body."
        }
    }
}

/// An error from the try-on service, with the code the server sent.
nonisolated struct TryOnFailure: LocalizedError, Equatable, Sendable {
    let code: String
    let message: String

    static let notConfigured = TryOnFailure(code: "not_configured", message: "The try-on service is not set up.")
    static let offline = TryOnFailure(code: "offline", message: "No connection to the try-on service.")

    var errorDescription: String? { userMessage }

    /// What the person using the app should read.
    var userMessage: String {
        switch code {
        case "pose_not_detected":
            return "The service couldn't see your body pose. Try a new avatar photo."
        case "content_blocked":
            return "This photo was blocked by the content filter."
        case "nothing_changed":
            return "The try-on didn't work with this photo. Try a clearer photo of the garment."
        case "bad_image":
            return "This photo couldn't be used. Try another one."
        case "category_not_supported":
            return "This kind of item can't be tried on yet."
        case "limit_reached":
            return "You've reached the try-on limit for now. It continues later by itself."
        case "provider_timeout", "provider_unavailable", "offline":
            return "The try-on service is busy. Tap to try again."
        case "not_configured":
            return "The try-on service is not set up."
        default:
            return "The try-on failed. Tap to try again."
        }
    }

    /// Failures that will hit every other garment too: stop the queue instead of repeating them.
    var stopsQueue: Bool {
        ["limit_reached", "provider_unavailable", "offline", "not_configured", "unauthorized"].contains(code)
    }
}

extension ClothingCategory {
    /// The category name the try-on server understands.
    var tryOnName: String {
        switch self {
        case .top:         return "top"
        case .bottom:      return "bottom"
        case .outerwear:   return "outerwear"
        case .shoes:       return "shoes"
        case .accessories: return "accessories"
        }
    }
}
