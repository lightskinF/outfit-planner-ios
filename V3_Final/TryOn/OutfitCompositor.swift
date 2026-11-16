import UIKit

/// Stacks garment layers on the avatar. No model, no network: just drawing.
nonisolated enum OutfitCompositor {

    /// - Parameters:
    ///   - base: the avatar on its backdrop.
    ///   - layers: layer files, innermost garment first.
    static func compose(base: URL, layers: [URL]) -> UIImage? {
        guard let avatar = UIImage(contentsOfFile: base.path) else { return nil }
        let size = TryOnStudio.canvasSize
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        format.preferredRange = .standard
        let frame = CGRect(origin: .zero, size: size)
        return UIGraphicsImageRenderer(size: size, format: format).image { _ in
            avatar.draw(in: frame)
            for url in layers {
                UIImage(contentsOfFile: url.path)?.draw(in: frame)
            }
        }
    }

    /// PNG of a garment photo, small enough to upload quickly.
    static func uploadData(for garment: UIImage, maxSide: CGFloat = 1024) -> Data? {
        let longest = max(garment.size.width * garment.scale, garment.size.height * garment.scale)
        guard longest > maxSide else { return garment.pngData() }
        let ratio = maxSide / longest
        let size = CGSize(width: (garment.size.width * garment.scale * ratio).rounded(),
                          height: (garment.size.height * garment.scale * ratio).rounded())
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = false
        format.preferredRange = .standard
        let resized = UIGraphicsImageRenderer(size: size, format: format).image { _ in
            garment.draw(in: CGRect(origin: .zero, size: size))
        }
        return resized.pngData()
    }
}
