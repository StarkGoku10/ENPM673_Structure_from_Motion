import open3d as o3d

def visualize_point_cloud_with_open3d(ply_file_path):
    # Load the point cloud
    pcd = o3d.io.read_point_cloud(ply_file_path)
    
    # Visualize the point cloud
    o3d.visualization.draw_geometries([pcd])

if __name__ == "__main__":
    ply_file_path = "Results\without bundle adjustment\\fountain-P11\\0000.ply"  # Update this path
    visualize_point_cloud_with_open3d(ply_file_path)